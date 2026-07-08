# db.py — Supabase (PostgreSQL via REST HTTPS, port 443)
# Fallback automatique vers fichiers locaux si variables absentes.

import os

_ready   = False
_enabled = False
_client  = None


def _init():
    global _ready, _enabled, _client
    if _ready:
        return
    _ready = True
    url = os.getenv("SUPABASE_URL", "").strip()
    # Préférer la service role key (bypass RLS côté serveur).
    # Fallback sur la clé anon si service key absente (dev local).
    key = (os.getenv("SUPABASE_SERVICE_KEY", "").strip()
           or os.getenv("SUPABASE_KEY", "").strip())
    if url and key:
        try:
            from supabase import create_client
            _client  = create_client(url, key)
            _enabled = True
            print("[DB] Connecté à Supabase ✓")
        except Exception as e:
            print(f"[DB] Échec connexion Supabase : {e}")
    else:
        print("[DB] SUPABASE_URL / SUPABASE_KEY absents — mode fichiers locaux")


def is_available() -> bool:
    _init()
    return _enabled


def log_db_error(prefix: str, table: str, exc: Exception):
    """
    Log une erreur Supabase de façon ACTIONNABLE : si la table (ou une
    colonne) n'existe pas — code PostgREST PGRST205, ou PGRST204 pour une
    colonne — c'est une migration SQL oubliée, et le message le dit
    explicitement au lieu d'un générique noyé dans les logs.

    Pourquoi : les erreurs de schéma sont avalées par des try/except
    fail-safe partout (l'app doit survivre sans la table) — mais un
    message générique a déjà masqué pendant des semaines l'absence de
    weekly_reports, donc aucun rapport hebdo envoyé sans que rien
    ne le signale clairement.
    """
    msg = str(exc)
    if "PGRST205" in msg or "PGRST204" in msg \
            or "Could not find" in msg:
        print(f"{prefix} ⚠️ TABLE/COLONNE MANQUANTE dans Supabase ('{table}') — "
              f"exécuter la migration SQL correspondante (voir doc/SUPABASE.md). "
              f"Détail : {msg}", flush=True)
    else:
        print(f"{prefix} erreur Supabase ({table}) : {msg}", flush=True)


def _apply_filter(query, filter: dict):
    for k, v in filter.items():
        query = query.eq(k, v)
    return query


def _project(docs: list, projection: dict | None) -> list:
    if not projection or not docs:
        return docs
    excludes = {k for k, v in projection.items() if v == 0}
    includes = {k for k, v in projection.items() if v == 1}
    result = []
    for doc in docs:
        if includes:
            result.append({k: v for k, v in doc.items() if k in includes})
        else:
            result.append({k: v for k, v in doc.items() if k not in excludes})
    return result


# ── Opérations génériques ─────────────────────────────────────────────────────

def find_one(collection: str, filter: dict, projection: dict = None) -> dict | None:
    _init()
    if not _enabled:
        return None
    q = _client.table(collection).select("*")
    q = _apply_filter(q, filter)
    r = q.limit(1).execute()
    docs = _project(r.data, projection)
    return docs[0] if docs else None


def find(collection: str, filter: dict, projection: dict = None) -> list:
    _init()
    if not _enabled:
        return []
    q = _client.table(collection).select("*")
    q = _apply_filter(q, filter)
    r = q.execute()
    return _project(r.data, projection)


def insert_one(collection: str, document: dict):
    _init()
    if not _enabled:
        return
    _client.table(collection).insert(document).execute()


def update_one(collection: str, filter: dict, update: dict, upsert: bool = False):
    _init()
    if not _enabled:
        return
    # Gère la syntaxe MongoDB {"$set": {...}}
    fields = update.get("$set", update)
    if upsert:
        _client.table(collection).upsert({**filter, **fields}).execute()
    else:
        q = _client.table(collection).update(fields)
        q = _apply_filter(q, filter)
        q.execute()


def delete_one(collection: str, filter: dict):
    _init()
    if not _enabled:
        return
    q = _client.table(collection).delete()
    q = _apply_filter(q, filter)
    q.execute()


def count_documents(collection: str, filter: dict) -> int:
    _init()
    if not _enabled:
        return 0
    q = _client.table(collection).select("*", count="exact")
    q = _apply_filter(q, filter)
    r = q.execute()
    return r.count or 0
