"""Local ML categorization — the fallback half (rules first, ML second).

In-process sklearn (TF-IDF on text + StandardScaler on amount → LogisticRegression).
The trained pipeline is a joblib file under the Data directory's `models/` folder; the one
`model_versions` row named ML_MODEL_NAME records which file is current and its sha256.
No network call at predict time.

Lifecycle:
  - a fresh install has no model; the first retrain (ten categorized transactions) mints one.
  - predict() lazily loads + caches the pipeline, reloading only when the current row
    points at a different file.
  - retrain() rebuilds from the transactions store, off the event loop, and replaces the file.
"""

import io
import warnings
from datetime import UTC, datetime

import joblib
import pandas as pd
import sklearn
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import ML_CONF_MIN, ML_MODEL_NAME
from .store import files
from .store.categories import categories
from .store.model_versions import model_versions
from .store.transactions import transactions

MIN_TRAIN_ROWS = 10

# The imported model was trained on sklearn 1.3.2; loading it on 1.5+ is verified-safe
# but warns. Silence just that warning — a local retrain mints a same-version model.
warnings.filterwarnings("ignore", category=InconsistentVersionWarning)

# In-memory cache: the loaded pipeline + the (path, sha256) it came from.
_pipeline = None
_cached_key = None


# --- storage -----------------------------------------------------------------

def _version_doc() -> dict | None:
    return model_versions.one({"name": ML_MODEL_NAME})


def store_model(model_bytes: bytes, meta: dict) -> dict:
    """Write the pickle under models/ (replacing any prior file for this model) and
    upsert the `model_versions` row."""
    prior = _version_doc()
    rel, sha = files.write_model(ML_MODEL_NAME, model_bytes)
    doc = {
        "name": ML_MODEL_NAME,
        "path": rel,
        "sha256": sha,
        "sklearn_version": sklearn.__version__,
        **meta,
    }
    if prior:
        model_versions.update(prior["_id"], doc)
        doc["_id"] = prior["_id"]
    else:
        doc["_id"] = model_versions.insert({"_id": ML_MODEL_NAME, **doc})
    # Drop the superseded file only after the new pointer is committed.
    if prior and prior.get("path") and prior["path"] != rel:
        files.delete_model_file(prior["path"])
    _invalidate()
    return doc


def _invalidate():
    global _pipeline, _cached_key
    _pipeline = None
    _cached_key = None


def get_model():
    """Return the cached pipeline, reloading from disk only when the current row points at
    a different file. None if no model has been imported yet."""
    global _pipeline, _cached_key
    doc = _version_doc()
    if not doc or not doc.get("path"):
        return None
    key = (doc["path"], doc.get("sha256"))
    if _pipeline is None or key != _cached_key:
        raw = files.read_model(doc)          # verifies the sha256
        _pipeline = joblib.load(io.BytesIO(raw))
        _cached_key = key
    return _pipeline


def is_trained() -> bool:
    """Whether a model file is pointed at — the Ledger's ML suggest button and the suggest
    panel read this, so a fresh database says "no model yet" instead of doing nothing."""
    doc = _version_doc()
    return bool(doc and doc.get("path"))


def labelled_rows() -> int:
    """How many transactions carry a Category — what a retrain would learn from."""
    rows = transactions.rows("SELECT COUNT(*) FROM transactions WHERE category IS NOT NULL AND category != ''")
    return int(rows[0][0]) if rows else 0


def model_info() -> dict:
    """What the Categorization page's ML model tab shows: the current pointer row (or
    None), whether a model is trained, the categorized rows a retrain would learn from, the
    confidence floor, and the minimum training rows. ML_CONF_MIN is read as the module
    global so a test (or a later settings page) can override it."""
    doc = _version_doc()
    model = None
    if doc:
        model = {k: doc.get(k) for k in ("name", "path", "sha256", "sklearn_version",
                                          "trained_at", "rows_trained", "n_categories",
                                          "filters_applied", "source")}
        for k in ("trained_at", "_edited_at"):
            v = doc.get(k)
            if hasattr(v, "isoformat"):
                model[k] = v.isoformat()
    return {"model": model, "trained": bool(model and model.get("path")), "labelled_rows": labelled_rows(),
            "conf_min": ML_CONF_MIN, "min_train_rows": MIN_TRAIN_ROWS}


# --- predict -----------------------------------------------------------------

def _amount(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def predict(description: str, amount=0.0) -> list[dict]:
    """Top-3 [{category, confidence}] for one transaction. [] if no model or no text."""
    description = (description or "").strip()
    if not description:
        return []
    pipeline = get_model()
    if pipeline is None:
        return []

    X = pd.DataFrame({"text": [description], "amount": [_amount(amount)]})
    proba = pipeline.predict_proba(X)[0]
    classes = pipeline.classes_
    top3 = proba.argsort()[-3:][::-1]
    out = [{"category": str(classes[i]), "confidence": round(float(proba[i]), 4)}
           for i in top3]
    return [p for p in out if p["confidence"] >= ML_CONF_MIN]


# --- retrain -----------------------------------------------------------------

def build_pipeline() -> Pipeline:
    """The exact preprocessing + classifier from the Cloud Function retrain."""
    pre = ColumnTransformer([
        ("tfidf", TfidfVectorizer(strip_accents="unicode", lowercase=True,
                                  ngram_range=(1, 2), min_df=1, sublinear_tf=True), "text"),
        ("amount", StandardScaler(), ["amount"]),
    ])
    return Pipeline([
        ("features", pre),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000,
                                          C=1.0, solver="saga", n_jobs=-1)),
    ])


def _fit_bytes(X, y) -> bytes:
    """Fit + pickle. Runs in a worker thread (blocking CPU work, off the loop)."""
    pipeline = build_pipeline()
    pipeline.fit(X, y)
    buf = io.BytesIO()
    joblib.dump(pipeline, buf)
    return buf.getvalue()


def _training_frame(filters: dict) -> pd.DataFrame:
    """Labelled rows from the transactions store; text = Full Description else Description."""
    start = datetime.fromisoformat(filters["start_date"]) if filters.get("start_date") else None
    end = datetime.fromisoformat(filters["end_date"]) if filters.get("end_date") else None
    records = []
    for d in transactions.labelled(accounts=filters.get("accounts"), start=start, end=end):
        text = (d.get("Full Description") or d.get("Description") or "").strip()
        cat = (d.get("Category") or "").strip()
        if text and cat:
            records.append({"text": text, "amount": _amount(d.get("Amount")), "category": cat})
    return pd.DataFrame(records)


def _canonical_categories() -> set[str]:
    return {c.strip() for c in categories.distinct("Category") if (c or "").strip()}


def retrain(filters: dict | None = None) -> dict:
    """Rebuild the model from the transactions store and replace the model file. Returns
    a summary or {error: ...} when there isn't enough labelled data."""
    filters = filters or {}
    df = _training_frame(filters)
    if len(df) < MIN_TRAIN_ROWS:
        return {"error": f"Not enough labelled rows ({len(df)}, need ≥ {MIN_TRAIN_ROWS})",
                "rows_found": len(df)}

    canonical = _canonical_categories()
    if canonical:
        unknown = sorted(set(df["category"]) - canonical)
        df = df[df["category"].isin(canonical)]
    else:
        unknown = []
    if len(df) < MIN_TRAIN_ROWS:
        return {"error": f"Only {len(df)} rows have a known category (need ≥ {MIN_TRAIN_ROWS})",
                "unknown_categories": unknown}

    model_bytes = _fit_bytes(df[["text", "amount"]], df["category"].tolist())
    meta = {
        "trained_at": datetime.now(UTC).isoformat(),
        "rows_trained": int(len(df)),
        "n_categories": int(df["category"].nunique()),
        "filters_applied": filters,
        "source": "sqlite:transactions",
    }
    store_model(model_bytes, meta)
    return {"status": "success", "unknown_categories": unknown, **meta}
