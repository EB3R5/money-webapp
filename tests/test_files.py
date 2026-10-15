"""The model file beside the database (app/store/files.py). Uploads are Blobs (tests/test_blobs.py)."""

import hashlib

import pytest

from app.store import files


def test_model_write_and_verified_read(store_db):
    rel, sha = files.write_model("category_model", b"pickle-bytes")
    assert rel == f"models/category_model-{sha[:8]}.joblib"
    assert sha == hashlib.sha256(b"pickle-bytes").hexdigest()
    assert (store_db / rel).exists()
    assert files.read_model({"path": rel, "sha256": sha}) == b"pickle-bytes"
    with pytest.raises(RuntimeError):
        files.read_model({"path": rel, "sha256": "0" * 64})
    with pytest.raises(ValueError):
        files.read_model({"path": "../money.sqlite", "sha256": sha})
    assert files.delete_model_file(rel) is True
