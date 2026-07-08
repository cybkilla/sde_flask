# portfolio/config_advisor.py — Seuils configurables des règles de conseil

_TABLE = "advisor_config"

DEFAULTS = {
    "stop_loss_pct":   -20.0,  # P&L % déclenchant le stop loss automatique
    "take_profit_pct":  15.0,  # P&L % pour prise de bénéfices partielle
    "score_acheter":    60.0,  # Score SDE min pour conseiller ACHETER (sans position)
    "score_vendre":     38.0,  # Score SDE max pour signal VENDRE fort (avec position)
    "rsi_renforcer":    42.0,  # RSI max pour déclencher un renforcement sur faiblesse
    "pnl_renforcer":    -5.0,  # P&L % min (négatif) pour autoriser un renforcement
    "score_tenir":      62.0,  # Score min pour conseiller TENIR haussier confirmé
    "var_tenir_eval":    3.0,  # Variation J+1 max (%) pour évaluer TENIR/SURVEILLER comme bon
}


def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def get_config(username: str) -> dict:
    """Retourne la config de l'utilisateur, avec les valeurs par défaut en fallback."""
    cfg = dict(DEFAULTS)
    if not _db_ok():
        return cfg
    try:
        from db import _init, _client
        _init()
        rows = (
            _client.table(_TABLE)
            .select("*")
            .eq("username", username)
            .limit(1)
            .execute()
            .data or []
        )
        if rows:
            row = rows[0]
            for key in DEFAULTS:
                if row.get(key) is not None:
                    cfg[key] = float(row[key])
    except Exception as e:
        from db import log_db_error
        log_db_error("[Config] get_config", _TABLE, e)
    return cfg


def save_config(username: str, values: dict) -> dict:
    """Upsert la config. Valide et borne les valeurs avant sauvegarde."""
    bounds = {
        "stop_loss_pct":   (-50.0, -1.0),
        "take_profit_pct": (5.0,   100.0),
        "score_acheter":   (40.0,  85.0),
        "score_vendre":    (20.0,  55.0),
        "rsi_renforcer":   (25.0,  55.0),
        "pnl_renforcer":   (-25.0, -1.0),
        "score_tenir":     (45.0,  85.0),
        "var_tenir_eval":  (1.0,   8.0),
    }
    row = {"username": username}
    for key, (lo, hi) in bounds.items():
        v = values.get(key)
        if v is not None:
            row[key] = max(lo, min(hi, float(v)))

    if not _db_ok():
        return row
    try:
        from db import _init, _client
        from datetime import datetime, timezone
        _init()
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = (
            _client.table(_TABLE)
            .upsert(row, on_conflict="username")
            .execute()
        )
        saved = result.data[0] if result.data else row
        print(f"[Config] Seuils sauvegardés pour {username}", flush=True)
        return saved
    except Exception as e:
        from db import log_db_error
        log_db_error("[Config] save_config", _TABLE, e)
        return row


def reset_config(username: str) -> bool:
    """Remet les valeurs par défaut (supprime la ligne custom)."""
    if not _db_ok():
        return False
    try:
        from db import _init, _client
        _init()
        _client.table(_TABLE).delete().eq("username", username).execute()
        return True
    except Exception as e:
        print(f"[Config] reset_config erreur : {e}", flush=True)
        return False
