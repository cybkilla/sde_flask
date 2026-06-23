# watchlist/watchlist.py
# Gestion de la liste de tickers surveillés par utilisateur.
# Stockage dans watchlist.json — simple et sans base de données.
# Utilise Pandas pour afficher la liste dans Streamlit.

import json
import pandas as pd
from pathlib  import Path
from datetime import datetime

# Fichiers de stockage
WL_FILE    = Path(__file__).parent / "watchlist.json"
SCORE_FILE = Path(__file__).parent / "last_scores.json"


def _load(path: Path) -> dict:
    """Charge un fichier JSON, retourne {} si absent."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save(path: Path, data: dict):
    """Sauvegarde un dict dans un fichier JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Watchlist ─────────────────────────────────────────────
def get_watchlist(username: str) -> list:
    """Retourne la liste des tickers surveillés par l'utilisateur."""
    data = _load(WL_FILE)
    return data.get(username, [])


def add_ticker(username: str, ticker: str, company: str = ""):
    """Ajoute un ticker à la watchlist de l'utilisateur."""
    data  = _load(WL_FILE)
    items = data.get(username, [])

    # Vérifie que le ticker n'est pas déjà dans la liste
    tickers_existants = [i["ticker"] for i in items]
    if ticker.upper() not in tickers_existants:
        items.append({
            "ticker":    ticker.upper(),
            "company":   company,
            "added_at":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
    data[username] = items
    _save(WL_FILE, data)


def remove_ticker(username: str, ticker: str):
    """Supprime un ticker de la watchlist."""
    data  = _load(WL_FILE)
    items = data.get(username, [])
    data[username] = [i for i in items
                      if i["ticker"] != ticker.upper()]
    _save(WL_FILE, data)


def get_watchlist_df(username: str) -> pd.DataFrame:
    """
    Retourne la watchlist sous forme de DataFrame Pandas.
    Affichable directement avec st.dataframe().
    """
    items = get_watchlist(username)
    if not items:
        return pd.DataFrame(columns=["ticker", "company", "added_at"])
    return pd.DataFrame(items)


# ── Derniers scores (pour détecter les changements) ────────
def get_last_score(ticker: str) -> dict:
    """Retourne le dernier score connu pour un ticker."""
    data = _load(SCORE_FILE)
    return data.get(ticker.upper(), {})


def save_last_score(ticker: str, score: float, reco: str, prix: float = None):
    """Sauvegarde le score, la recommandation et le prix actuels."""
    data = _load(SCORE_FILE)
    entry = {
        "score":    score,
        "reco":     reco,
        "updated":  datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if prix is not None:
        entry["prix"] = round(prix, 4)
    data[ticker.upper()] = entry
    _save(SCORE_FILE, data)
    