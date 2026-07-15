# portfolio/history.py — Snapshots quotidiens de la valeur du portefeuille

_TABLE = "portfolio_snapshots"


def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def _market_closed_today() -> bool:
    """Retourne True si le NASDAQ a clôturé aujourd'hui (après 22h00 Paris, weekday)."""
    try:
        import zoneinfo
        from datetime import datetime
        paris = zoneinfo.ZoneInfo("Europe/Paris")
        now   = datetime.now(paris)
        return now.weekday() < 5 and now.hour >= 22
    except Exception:
        return False


def snapshot_exists_today(username: str) -> bool:
    """Vérifie si un snapshot a déjà été sauvegardé aujourd'hui pour cet utilisateur."""
    if not _db_ok():
        return True   # Ne pas bloquer si Supabase indispo
    try:
        from db import _init, _client
        from datetime import date
        _init()
        rows = (
            _client.table(_TABLE)
            .select("id")
            .eq("username", username)
            .eq("snapshot_date", str(date.today()))
            .limit(1)
            .execute()
            .data or []
        )
        return bool(rows)
    except Exception as e:
        print(f"[History] snapshot_exists_today erreur : {e}", flush=True)
        return True


def save_daily_snapshot(username: str, positions: list) -> bool:
    """
    Calcule et sauvegarde la valeur du portefeuille à ce moment.
    Regroupé par devise. Un snapshot par (username, date, currency).
    `positions` : liste de dicts tels que retournés par /portfolio/overview.
    """
    if not _db_ok() or not positions:
        return False
    try:
        from db import _init, _client
        from datetime import date
        _init()
        today = str(date.today())

        # Regrouper par devise
        by_cur: dict = {}
        for pos in positions:
            cur = pos.get("currency", "USD")
            g   = by_cur.setdefault(cur, {
                "portfolio_val": 0.0,
                "cash_dispo":    0.0,
                "pnl_cumul":     0.0,
            })
            s = pos.get("summary", {})
            if not s.get("position_fermee"):
                g["portfolio_val"] += float(s.get("valeur_actuelle") or 0)
            # Cash suivi = ventes − achats (convention utilisateur : un lot
            # 'achat' est financé par le cash suivi ; 'import' = cash
            # externe, exclu). L'ancienne formule (ventes seules) comptait
            # le compte en DOUBLE après un réinvestissement : cash non
            # décrémenté + valeur de la nouvelle position.
            for l in (s.get("lots") or []):
                montant = float(l.get("quantite") or 0) * float(l.get("prix_achat") or 0)
                if l.get("type") == "vente":
                    g["cash_dispo"] += montant
                elif l.get("type", "achat") == "achat":
                    g["cash_dispo"] -= montant
            g["pnl_cumul"] += float(s.get("pnl_euros") or 0)

        rows = []
        for cur, g in by_cur.items():
            # Convention respectée → jamais négatif ; si ça arrive quand
            # même (achat externe saisi en 'achat'), on plancher à 0 pour
            # ne pas fausser le total_compte vers le bas
            if g["cash_dispo"] < 0:
                print(f"[History] cash suivi négatif ({g['cash_dispo']:.2f} {cur}) "
                      f"pour {username} — plancher à 0 (achat externe saisi en "
                      f"'achat' ? utiliser 'import')", flush=True)
                g["cash_dispo"] = 0.0
            rows.append({
                "username":     username,
                "snapshot_date": today,
                "currency":     cur,
                "portfolio_val": round(g["portfolio_val"], 2),
                "cash_dispo":   round(g["cash_dispo"],    2),
                "total_compte": round(g["portfolio_val"] + g["cash_dispo"], 2),
                "pnl_cumul":    round(g["pnl_cumul"],     2),
            })

        if rows:
            _client.table(_TABLE)\
                .upsert(rows, on_conflict="username,snapshot_date,currency")\
                .execute()
            print(f"[History] Snapshot {today} sauvegardé pour {username} "
                  f"({len(rows)} devise(s))", flush=True)
        return True
    except Exception as e:
        print(f"[History] save_daily_snapshot erreur : {e}", flush=True)
        return False


def get_history(username: str, days: int = 90) -> list:
    """Retourne les snapshots des N derniers jours, les plus récents en dernier."""
    if not _db_ok():
        return []
    try:
        from db import _init, _client
        from datetime import date, timedelta
        _init()
        since = str(date.today() - timedelta(days=days))
        rows  = (
            _client.table(_TABLE)
            .select("snapshot_date,currency,portfolio_val,cash_dispo,total_compte,pnl_cumul")
            .eq("username", username)
            .gte("snapshot_date", since)
            .order("snapshot_date")
            .execute()
            .data or []
        )
        return rows
    except Exception as e:
        print(f"[History] get_history erreur : {e}", flush=True)
        return []
