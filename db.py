# db.py — MongoDB Atlas Data API (HTTPS port 443)
# Évite les problèmes TLS sur port 27017 dans certains environnements Docker.
# Fallback automatique vers fichiers locaux si variables absentes.

import os, requests

_BASE = "https://data.mongodb-api.com/app/{app_id}/endpoint/data/v1/action"
_DB   = "sde"
_ready = False
_enabled = False
_app_id  = ""
_api_key  = ""


def _init():
    global _ready, _enabled, _app_id, _api_key
    if _ready:
        return
    _ready   = True
    _app_id  = os.getenv("ATLAS_APP_ID",  "").strip()
    _api_key = os.getenv("ATLAS_API_KEY", "").strip()
    if _app_id and _api_key:
        _enabled = True
        print("[DB] Atlas Data API configurée ✓")
    else:
        print("[DB] ATLAS_APP_ID / ATLAS_API_KEY absents — mode fichiers locaux")


def _url(action: str) -> str:
    return _BASE.format(app_id=_app_id) + "/" + action


def _headers() -> dict:
    return {"Content-Type": "application/json", "api-key": _api_key}


def is_available() -> bool:
    _init()
    return _enabled


# ── Opérations génériques ─────────────────────────────────────────────────────

def find_one(collection: str, filter: dict, projection: dict = None) -> dict | None:
    _init()
    if not _enabled:
        return None
    body = {"dataSource": "sde-cluster", "database": _DB,
            "collection": collection, "filter": filter}
    if projection:
        body["projection"] = projection
    r = requests.post(_url("findOne"), json=body, headers=_headers(), timeout=8)
    r.raise_for_status()
    return r.json().get("document")


def find(collection: str, filter: dict, projection: dict = None) -> list:
    _init()
    if not _enabled:
        return []
    body = {"dataSource": "sde-cluster", "database": _DB,
            "collection": collection, "filter": filter}
    if projection:
        body["projection"] = projection
    r = requests.post(_url("find"), json=body, headers=_headers(), timeout=8)
    r.raise_for_status()
    return r.json().get("documents", [])


def insert_one(collection: str, document: dict):
    _init()
    if not _enabled:
        return
    body = {"dataSource": "sde-cluster", "database": _DB,
            "collection": collection, "document": document}
    r = requests.post(_url("insertOne"), json=body, headers=_headers(), timeout=8)
    r.raise_for_status()


def update_one(collection: str, filter: dict, update: dict, upsert: bool = False):
    _init()
    if not _enabled:
        return
    body = {"dataSource": "sde-cluster", "database": _DB,
            "collection": collection, "filter": filter,
            "update": update, "upsert": upsert}
    r = requests.post(_url("updateOne"), json=body, headers=_headers(), timeout=8)
    r.raise_for_status()


def delete_one(collection: str, filter: dict):
    _init()
    if not _enabled:
        return
    body = {"dataSource": "sde-cluster", "database": _DB,
            "collection": collection, "filter": filter}
    r = requests.post(_url("deleteOne"), json=body, headers=_headers(), timeout=8)
    r.raise_for_status()


def count_documents(collection: str, filter: dict) -> int:
    docs = find(collection, filter)
    return len(docs)
