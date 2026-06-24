# db.py — connexion MongoDB Atlas (singleton)
# Si MONGO_URI est défini → MongoDB (production)
# Si absent ou inaccessible → None (fallback fichiers locaux pour dev)

import os

_db      = None
_ready   = False   # True = tentative déjà faite (succès ou échec)

def get_db():
    """Retourne l'objet Database MongoDB, ou None si non configuré / inaccessible."""
    global _db, _ready
    if _ready:
        return _db          # déjà tenté — on ne réessaie pas à chaque requête

    _ready = True
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        print("[DB] MONGO_URI absent — mode fichiers locaux")
        return None

    try:
        from pymongo import MongoClient
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        _db = client["sde"]
        print("[DB] Connecté à MongoDB Atlas ✓")
    except Exception as exc:
        print(f"[DB] Échec connexion MongoDB : {exc}")
        print("[DB] Fallback : fichiers locaux (YAML / JSON)")
        _db = None

    return _db
