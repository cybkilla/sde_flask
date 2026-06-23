# cache.py
# Cache en mémoire avec TTL (time-to-live).
# Évite les appels API répétés quand l'utilisateur
# actualise la page Streamlit sans changer de ticker.

import time
import pandas as pd
from typing import Optional

# Stockage en mémoire : {ticker: {"data": ..., "ts": timestamp}}
_CACHE: dict = {}


def get_cached(ticker: str) -> Optional[dict]:
    """
    Retourne le résultat mis en cache si encore valide.
    Retourne None si absent ou expiré.
    """
    entry = _CACHE.get(ticker.upper())
    if not entry:
        return None

    # Vérifie que le cache n'est pas expiré
    age_sec = time.time() - entry["ts"]
    if age_sec > entry["ttl_sec"]:
        del _CACHE[ticker.upper()]   # purge automatique
        return None

    return entry["data"]


def set_cached(ticker: str, data: dict, ttl_minutes: int = 15):
    """Stocke le résultat avec un timestamp et un TTL."""
    _CACHE[ticker.upper()] = {
        "data":    data,
        "ts":      time.time(),
        "ttl_sec": ttl_minutes * 60,
    }


def clear_cache():
    """Vide tout le cache (ex. bouton « Régénérer » sur l'explication LLM)."""
    _CACHE.clear()


def cache_stats() -> pd.DataFrame:
    """
    Retourne un DataFrame Pandas avec l'état du cache.
    Utile pour le debug en mode développement.
    """
    now = time.time()
    rows = []
    for k, v in _CACHE.items():
        age  = round((now - v["ts"]) / 60, 1)
        reste = round((v["ttl_sec"] - (now - v["ts"])) / 60, 1)
        rows.append({"ticker": k, "age_min": age, "reste_min": reste})
    return pd.DataFrame(rows) if rows else pd.DataFrame()
