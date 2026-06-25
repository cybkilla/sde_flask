# portfolio/evaluator.py — Évaluation automatique des conseils passés
# Compare le prix J+1 avec le prix du conseil pour juger la pertinence.

from datetime import date, datetime, timezone, timedelta
from collections import defaultdict


def evaluate_pending(days_back: int = 60) -> dict:
    """
    Évalue tous les conseils non évalués des `days_back` derniers jours.
    Requiert Supabase. Utilise yfinance pour les prix de clôture J+1.
    Retourne {"evaluated": int, "skipped": int, "errors": int}.
    """
    from db import _init, _client, is_available
    if not is_available():
        return {"evaluated": 0, "skipped": 0, "errors": 0}

    _init()
    today   = date.today()
    cutoff  = str(today - timedelta(days=days_back))

    # Toutes les lignes non évaluées antérieures à aujourd'hui
    rows = (
        _client.table("daily_advice")
        .select("id,username,ticker,date_conseil,action,prix_jour,bon_conseil")
        .is_("bon_conseil", "null")
        .gte("date_conseil", cutoff)
        .lt("date_conseil", str(today))
        .execute()
        .data or []
    )

    if not rows:
        return {"evaluated": 0, "skipped": 0, "errors": 0}

    # Grouper par ticker pour limiter les appels yfinance
    by_ticker = defaultdict(list)
    for row in rows:
        if row.get("prix_jour"):
            by_ticker[row["ticker"]].append(row)

    evaluated = skipped = errors = 0

    import yfinance as yf

    for ticker, ticker_rows in by_ticker.items():
        try:
            min_date = min(r["date_conseil"] for r in ticker_rows)
            # Récupère l'historique depuis min_date jusqu'à aujourd'hui
            hist = yf.Ticker(ticker).history(
                start=min_date,
                end=str(today + timedelta(days=1)),
                auto_adjust=True,
            )
            if hist.empty:
                skipped += len(ticker_rows)
                continue

            # Normalise l'index en dates sans timezone
            if hist.index.tz is not None:
                hist.index = hist.index.tz_convert(None)
            hist.index = hist.index.normalize()

            for row in ticker_rows:
                try:
                    d_conseil = datetime.strptime(row["date_conseil"], "%Y-%m-%d")
                    # Prochain jour de cotation après la date du conseil
                    suivants = hist[hist.index > d_conseil]
                    if suivants.empty:
                        skipped += 1
                        continue

                    prix_j1 = float(suivants.iloc[0]["Close"])
                    prix_j0 = float(row["prix_jour"])
                    if prix_j0 == 0:
                        skipped += 1
                        continue

                    variation = round((prix_j1 - prix_j0) / prix_j0 * 100, 2)
                    action    = row.get("action", "")

                    if action in ("ACHETER", "RENFORCER"):
                        bon = variation > 0
                    elif action in ("VENDRE", "ALLÉGER"):
                        bon = variation < 0
                    elif action in ("TENIR", "SURVEILLER"):
                        bon = abs(variation) < 3
                    else:
                        skipped += 1
                        continue

                    _client.table("daily_advice").update({
                        "prix_j1":      round(prix_j1, 4),
                        "variation_j1": variation,
                        "bon_conseil":  bon,
                        "evaluated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", row["id"]).execute()

                    evaluated += 1
                    emoji = "✓" if bon else "✗"
                    print(f"[Evaluator] {ticker} {row['date_conseil']} {action} {emoji}"
                          f" var={variation:+.1f}%", flush=True)

                except Exception as re:
                    print(f"[Evaluator] {ticker} row erreur : {re}", flush=True)
                    errors += 1

        except Exception as te:
            print(f"[Evaluator] {ticker} erreur yfinance : {te}", flush=True)
            errors += len(ticker_rows)

    return {"evaluated": evaluated, "skipped": skipped, "errors": errors}


def get_global_stats() -> dict:
    """
    Agrège les stats de pertinence sur tous les utilisateurs et tickers.
    Retourne global %, breakdown par action, par ticker.
    """
    from db import _init, _client, is_available
    if not is_available():
        return {}

    _init()
    rows = (
        _client.table("daily_advice")
        .select("ticker,action,bon_conseil,variation_j1,date_conseil,username")
        .not_.is_("bon_conseil", "null")
        .execute()
        .data or []
    )

    if not rows:
        return {"total": 0, "bons": 0, "mauvais": 0, "taux_pct": None,
                "by_action": {}, "by_ticker": []}

    total   = len(rows)
    bons    = sum(1 for r in rows if r["bon_conseil"])
    mauvais = total - bons
    taux    = round(bons / total * 100, 1) if total else None

    # ── Par action ──
    action_stats: dict[str, dict] = {}
    for r in rows:
        a = r.get("action", "?")
        s = action_stats.setdefault(a, {"total": 0, "bons": 0})
        s["total"] += 1
        if r["bon_conseil"]:
            s["bons"] += 1
    for a, s in action_stats.items():
        s["taux_pct"] = round(s["bons"] / s["total"] * 100, 1) if s["total"] else None

    # ── Par ticker ──
    ticker_stats: dict[str, dict] = {}
    for r in rows:
        t = r["ticker"]
        s = ticker_stats.setdefault(t, {"ticker": t, "total": 0, "bons": 0,
                                        "last_date": "", "last_action": ""})
        s["total"] += 1
        if r["bon_conseil"]:
            s["bons"] += 1
        if r["date_conseil"] > s["last_date"]:
            s["last_date"]   = r["date_conseil"]
            s["last_action"] = r["action"]

    for s in ticker_stats.values():
        s["taux_pct"] = round(s["bons"] / s["total"] * 100, 1) if s["total"] else None

    ticker_list = sorted(ticker_stats.values(), key=lambda x: -x["total"])

    return {
        "total":     total,
        "bons":      bons,
        "mauvais":   mauvais,
        "taux_pct":  taux,
        "by_action": action_stats,
        "by_ticker": ticker_list,
    }
