# watchlist/watchlist.py
# Stockage MongoDB (si MONGO_URI défini) ou JSON local (dev sans MongoDB)

import json
import pandas as pd
from pathlib  import Path
from datetime import datetime

WL_FILE    = Path(__file__).parent / "watchlist.json"
SCORE_FILE = Path(__file__).parent / "last_scores.json"


# ── Backend MongoDB (Data API) ────────────────────────────────────────────────

def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


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
    if _db_ok():
        try:
            from db import find
            docs = find("watchlist", {"username": username}, {"_id": 0, "username": 0})
            return docs
        except Exception:
            pass
    return _jload(WL_FILE).get(username, [])


def add_ticker(username: str, ticker: str, company: str = ""):
    ticker = ticker.upper()
    if _db_ok():
        try:
            from db import find_one, insert_one
            existing = find_one("watchlist", {"username": username, "ticker": ticker})
            if not existing:
                insert_one("watchlist", {
                    "username": username, "ticker": ticker,
                    "company":  company,
                    "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
            return
        except Exception:
            pass
    data  = _jload(WL_FILE)
    items = data.get(username, [])
    if ticker not in [i["ticker"] for i in items]:
        items.append({"ticker": ticker, "company": company,
                      "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
    data[username] = items
    _jsave(WL_FILE, data)


def remove_ticker(username: str, ticker: str):
    ticker = ticker.upper()
    if _db_ok():
        try:
            from db import delete_one
            delete_one("watchlist", {"username": username, "ticker": ticker})
            return
        except Exception:
            pass
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
    if _db_ok():
        try:
            from db import find_one
            doc = find_one("scores", {"ticker": ticker}, {"_id": 0, "ticker": 0})
            return doc or {}
        except Exception:
            pass
    return _jload(SCORE_FILE).get(ticker, {})


def save_last_score(ticker: str, score: float, reco: str, prix: float = None):
    ticker = ticker.upper()
    entry  = {"score": score, "reco": reco,
               "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if prix is not None:
        entry["prix"] = round(prix, 4)

    if _db_ok():
        try:
            from db import update_one
            update_one("scores", {"ticker": ticker}, {"$set": entry}, upsert=True)
            return
        except Exception:
            pass
    data = _jload(SCORE_FILE)
    data[ticker] = entry
    _jsave(SCORE_FILE, data)
