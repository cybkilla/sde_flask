# watchlist/watchlist.py
# Stockage MongoDB (si MONGO_URI défini) ou JSON local (dev sans MongoDB)

import json
import pandas as pd
from pathlib  import Path
from datetime import datetime

WL_FILE    = Path(__file__).parent / "watchlist.json"
SCORE_FILE = Path(__file__).parent / "last_scores.json"


# ── Backend MongoDB ───────────────────────────────────────────────────────────

def _col_wl():
    try:
        from db import get_db
        db = get_db()
        return db["watchlist"] if db is not None else None
    except Exception:
        return None


def _col_scores():
    try:
        from db import get_db
        db = get_db()
        return db["scores"] if db is not None else None
    except Exception:
        return None


# ── Backend JSON local (fallback dev) ─────────────────────────────────────────

def _jload(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _jsave(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Watchlist ─────────────────────────────────────────────────────────────────

def get_watchlist(username: str) -> list:
    col = _col_wl()
    if col is not None:
        docs = col.find({"username": username}, {"_id": 0, "username": 0})
        return list(docs)
    return _jload(WL_FILE).get(username, [])


def add_ticker(username: str, ticker: str, company: str = ""):
    ticker = ticker.upper()
    col = _col_wl()
    if col is not None:
        col.update_one(
            {"username": username, "ticker": ticker},
            {"$setOnInsert": {
                "username": username,
                "ticker":   ticker,
                "company":  company,
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }},
            upsert=True,
        )
        return
    data  = _jload(WL_FILE)
    items = data.get(username, [])
    if ticker not in [i["ticker"] for i in items]:
        items.append({"ticker": ticker, "company": company,
                      "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
    data[username] = items
    _jsave(WL_FILE, data)


def remove_ticker(username: str, ticker: str):
    ticker = ticker.upper()
    col = _col_wl()
    if col is not None:
        col.delete_one({"username": username, "ticker": ticker})
        return
    data = _jload(WL_FILE)
    data[username] = [i for i in data.get(username, []) if i["ticker"] != ticker]
    _jsave(WL_FILE, data)


def get_watchlist_df(username: str) -> pd.DataFrame:
    items = get_watchlist(username)
    if not items:
        return pd.DataFrame(columns=["ticker", "company", "added_at"])
    return pd.DataFrame(items)


# ── Derniers scores ───────────────────────────────────────────────────────────

def get_last_score(ticker: str) -> dict:
    ticker = ticker.upper()
    col = _col_scores()
    if col is not None:
        doc = col.find_one({"ticker": ticker}, {"_id": 0, "ticker": 0})
        return doc or {}
    return _jload(SCORE_FILE).get(ticker, {})


def save_last_score(ticker: str, score: float, reco: str, prix: float = None):
    ticker = ticker.upper()
    entry  = {"score": score, "reco": reco,
               "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if prix is not None:
        entry["prix"] = round(prix, 4)

    col = _col_scores()
    if col is not None:
        col.update_one({"ticker": ticker}, {"$set": entry}, upsert=True)
        return
    data = _jload(SCORE_FILE)
    data[ticker] = entry
    _jsave(SCORE_FILE, data)
