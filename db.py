# db.py — connexion MongoDB Atlas (singleton)
# Si MONGO_URI est défini → MongoDB (production)
# Si absent → None (l'app retombe sur fichiers locaux pour le dev)

import os

_client = None
_db     = None

def get_db():
    """Retourne l'objet Database MongoDB, ou None si MONGO_URI non configuré."""
    global _client, _db
    if _db is not None:
        return _db
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        return None
    try:
        from pymongo import MongoClient
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")   # vérifie la connexion au démarrage
        _db = _client["sde"]
        print("[DB] Connecté à MongoDB Atlas ✓")
    except Exception as exc:
        print(f"[DB] Échec connexion MongoDB : {exc} — fallback fichiers locaux")
        _db = None
    return _db
