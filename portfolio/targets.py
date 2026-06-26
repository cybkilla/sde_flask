# portfolio/targets.py — Take Profit / Stop Loss personnalisés par position

_TABLE = "position_targets"


def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def get_targets(username: str, ticker: str) -> dict | None:
    """Retourne {take_profit, stop_loss, tp_alerted_at, sl_alerted_at} ou None."""
    if not _db_ok():
        return None
    try:
        from db import _init, _client
        _init()
        rows = (
            _client.table(_TABLE)
            .select("*")
            .eq("username", username)
            .eq("ticker", ticker.upper())
            .limit(1)
            .execute()
            .data or []
        )
        return rows[0] if rows else None
    except Exception as e:
        print(f"[Targets] get_targets erreur : {e}", flush=True)
        return None


def save_targets(username: str, ticker: str,
                 take_profit: float | None, stop_loss: float | None) -> dict:
    """Upsert les niveaux TP/SL. Réinitialise les flags d'alerte à chaque modif.
    Lève une exception si la DB est indisponible ou si l'upsert échoue."""
    if not _db_ok():
        raise RuntimeError("Base de données non disponible")
    from db import _init, _client
    from datetime import datetime, timezone
    _init()
    row = {
        "username":       username,
        "ticker":         ticker.upper(),
        "take_profit":    round(float(take_profit), 4) if take_profit else None,
        "stop_loss":      round(float(stop_loss),   4) if stop_loss  else None,
        "tp_alerted_at":  None,
        "sl_alerted_at":  None,
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }
    result = (
        _client.table(_TABLE)
        .upsert(row, on_conflict="username,ticker")
        .execute()
    )
    return result.data[0] if result.data else row


def delete_targets(username: str, ticker: str) -> bool:
    """Supprime les targets d'un ticker."""
    if not _db_ok():
        return False
    try:
        from db import _init, _client
        _init()
        _client.table(_TABLE).delete()\
            .eq("username", username).eq("ticker", ticker.upper()).execute()
        return True
    except Exception as e:
        print(f"[Targets] delete_targets erreur : {e}", flush=True)
        return False


def check_and_alert(username: str, ticker: str, company: str,
                    prix_live: float, email: str) -> None:
    """
    Vérifie si prix_live franchit le TP ou le SL.
    Envoie une alerte email et enregistre l'heure pour éviter le re-spam (24h).
    """
    if not _db_ok() or not prix_live or not email:
        return
    targets = get_targets(username, ticker)
    if not targets:
        return

    tp = targets.get("take_profit")
    sl = targets.get("stop_loss")
    if not tp and not sl:
        return

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)

    def _alerted_recently(ts_str) -> bool:
        if not ts_str:
            return False
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return (now - ts) < timedelta(hours=24)
        except Exception:
            return False

    try:
        from db import _init, _client
        from alerts.mailer import send_tp_sl_alert
        _init()

        if tp and prix_live >= tp and not _alerted_recently(targets.get("tp_alerted_at")):
            send_tp_sl_alert(
                to_email=email, username=username,
                ticker=ticker, company=company,
                level_type="take_profit",
                prix_live=prix_live, prix_cible=tp,
            )
            _client.table(_TABLE).update({"tp_alerted_at": now.isoformat()})\
                .eq("username", username).eq("ticker", ticker.upper()).execute()
            print(f"[Targets] TP atteint {ticker} ({prix_live:.2f} >= {tp:.2f})", flush=True)

        if sl and prix_live <= sl and not _alerted_recently(targets.get("sl_alerted_at")):
            send_tp_sl_alert(
                to_email=email, username=username,
                ticker=ticker, company=company,
                level_type="stop_loss",
                prix_live=prix_live, prix_cible=sl,
            )
            _client.table(_TABLE).update({"sl_alerted_at": now.isoformat()})\
                .eq("username", username).eq("ticker", ticker.upper()).execute()
            print(f"[Targets] SL atteint {ticker} ({prix_live:.2f} <= {sl:.2f})", flush=True)

    except Exception as e:
        print(f"[Targets] check_and_alert erreur ({ticker}) : {e}", flush=True)
