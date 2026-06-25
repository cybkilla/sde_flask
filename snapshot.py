# snapshot.py — Cache persistant Supabase pour les résultats pipeline.
# Couche entre le cache in-memory (15 min) et le pipeline complet.
# Durée de vie : MAX_AGE_HOURS (12h par défaut).

import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

_TABLE        = "ticker_snapshots"
MAX_AGE_HOURS = 24   # pipeline complet max 1×/jour par ticker


# ── Sérialisation ─────────────────────────────────────────────────────────────

def _v(val):
    """Scalaire numpy/pandas → type Python natif JSON-safe."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return None if math.isnan(float(val)) else float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    return val


def _df_to_records(df) -> list:
    """DataFrame pandas → liste de dicts JSON-safe."""
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return []
    records = df.reset_index().to_dict(orient="records")
    return [{k: _v(v) for k, v in row.items()} for row in records]


def _clean(obj):
    """Convertit récursivement n'importe quel objet en JSON-safe.
    Gère les DataFrames et Series imbriqués dans des dicts (ex: executive_risk["detail"]).
    """
    if isinstance(obj, pd.DataFrame):
        return _df_to_records(obj)
    if isinstance(obj, pd.Series):
        return {str(i): _v(x) for i, x in obj.items()}
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    return _v(obj)


def _serialize(result: dict) -> dict:
    """Transforme le dict pipeline en JSON pur stockable dans Supabase."""
    out = {}
    for key, val in result.items():
        if key.startswith("_sde"):          # méta-champs internes, non persistés
            continue
        if key == "market":
            m = {k: _v(v) for k, v in val.items() if k != "history"}
            m["history"] = _df_to_records(val.get("history"))
            out["market"] = m
        else:
            out[key] = _clean(val)
    return out


def _records_to_df(records: list, date_col: str = None) -> pd.DataFrame:
    """Liste de dicts → DataFrame pandas."""
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if date_col and date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col]).dt.tz_localize(None)
        df = df.set_index(date_col)
    return df


def _deserialize(data: dict) -> dict:
    """Reconstruit le dict pipeline depuis le JSON Supabase."""
    out = dict(data)

    # market : history → DatetimeIndex "Date"
    m = dict(out.get("market", {}))
    m["history"] = _records_to_df(m.pop("history", []), date_col="Date")
    out["market"] = m

    # sentiment : df_annote → DataFrame simple
    s = dict(out.get("sentiment", {}))
    if isinstance(s.get("df_annote"), list):
        s["df_annote"] = pd.DataFrame(s["df_annote"]) if s["df_annote"] else pd.DataFrame()
    out["sentiment"] = s

    # DataFrames sans index date
    out["df_news"]    = _records_to_df(out.get("df_news",    []))
    out["df_insider"] = _records_to_df(out.get("df_insider", []))
    out["df_events"]  = _records_to_df(out.get("df_events",  []))
    out["df_scores"]  = _records_to_df(out.get("df_scores",  []))

    return out


# ── API publique ──────────────────────────────────────────────────────────────

def get_snapshot(ticker: str, max_age_hours: int = MAX_AGE_HOURS) -> dict | None:
    """
    Cherche un snapshot Supabase pour ce ticker.
    Retourne le dict pipeline désérialisé si frais (< max_age_hours), None sinon.
    Injecte _sde_snapshot_age_min dans le résultat pour que la route puisse
    décider de rafraîchir le prix live.
    """
    try:
        from db import find_one, is_available
        if not is_available():
            return None

        row = find_one(_TABLE, {"ticker": ticker.upper()})
        if not row or not row.get("data"):
            return None

        refreshed_at = row.get("refreshed_at", "")
        if isinstance(refreshed_at, str):
            refreshed_at = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
        age     = datetime.now(timezone.utc) - refreshed_at.astimezone(timezone.utc)
        age_min = int(age.total_seconds() / 60)

        if age > timedelta(hours=max_age_hours):
            print(f"[Snapshot] {ticker} expiré ({age_min} min) — pipeline complet", flush=True)
            return None

        print(f"[Snapshot] {ticker} hit Supabase (âge {age_min} min)", flush=True)
        result = _deserialize(row["data"])
        result["_sde_snapshot_age_min"] = age_min
        result["_sde_snapshot_ts"]      = refreshed_at.isoformat()
        return result

    except Exception as e:
        print(f"[Snapshot] get_snapshot erreur : {e}", flush=True)
        return None


def save_snapshot(ticker: str, result: dict):
    """Sérialise et upsert le résultat pipeline dans Supabase (silencieux si indisponible)."""
    try:
        from db import update_one, is_available
        if not is_available():
            return

        payload = {
            "data":         _serialize(result),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        update_one(
            _TABLE,
            {"ticker": ticker.upper()},
            {"$set": payload},
            upsert=True,
        )
        print(f"[Snapshot] {ticker} sauvegardé dans Supabase ✓", flush=True)

    except Exception as e:
        print(f"[Snapshot] save_snapshot erreur : {e}", flush=True)
