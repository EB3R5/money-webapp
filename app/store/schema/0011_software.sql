-- Software (ADR-0017): software the user has — installed, subscribed, in use. One row per
-- package identity (source_key: pacman:ripgrep, github:owner/repo, appstore:904280696, …)
-- or a hand-made card. The modal writes the form fields; the stored-only facts
-- (install_locations, version_latest, stars, topics, import_status, …) are written by the
-- import endpoint and the clipper's facts route, never the modal. `images` is the photo
-- entry list (files under DATA_DIR/photos/<id>/, like inventory).
CREATE TABLE software (
    id                 TEXT PRIMARY KEY,
    sw_id              TEXT,        -- SW-### minted by the app (the business id)
    item_name          TEXT,
    status             TEXT,        -- using | trialing | installed_unused | cancelled | uninstalled
    kind               TEXT,        -- app | cli | library | extension | saas | os_package
    vendor             TEXT,
    category           TEXT,
    license_type       TEXT,        -- free | oss | perpetual | subscription | trial
    billing_cadence    TEXT,        -- none | monthly | yearly | one_time
    cost               REAL,        -- per cadence period; one_time = purchase price
    version_installed  TEXT,
    link               TEXT,        -- the ↗ target: store / repo / homepage page
    source_key         TEXT,        -- source:key — import + clip identity; NULL for a plain manual card
    merchant_match     TEXT,        -- reserved: bank-statement substring for the ledger link
    description        TEXT,
    notes              TEXT,
    homepage           TEXT,
    repo_url           TEXT,
    license_id         TEXT,        -- SPDX id
    bundle_id          TEXT,        -- macOS reverse-DNS bundle id
    currency           TEXT,
    version_latest     TEXT,
    stars              INTEGER,
    topics             TEXT,        -- JSON list of strings
    archived           INTEGER,     -- bool: upstream repo archived
    install_locations  TEXT,        -- JSON list of {host, manager, id, version, seen_at}
    last_used          TEXT,
    use_count          INTEGER,
    import_status      TEXT,        -- the last Status the importer set (API: _import_status)
    refreshed_at       TEXT,        -- ISO datetime of the last registry fetch (API: _refreshed_at)
    images             TEXT,        -- JSON list of {id, filename, content_type}
    src                TEXT,        -- manual | import | clip (API: _src)
    created_at         TEXT,
    edited_at          TEXT
);
CREATE UNIQUE INDEX ux_software_source_key ON software(source_key) WHERE source_key IS NOT NULL;
CREATE INDEX ix_software_status ON software(status);
