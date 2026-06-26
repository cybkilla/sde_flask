# portfolio/evaluator.py — Évaluation automatique des conseils passés
# Compare le prix J+1 avec le prix du conseil pour juger la pertinence.

from datetime import date, datetime, timezone, timedelta
from collections import defaultdict


def _market_open_now() -> bool:
    """Retourne True si le NASDAQ est actuellement ouvert (heure Paris)."""
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("Europe/Paris"))
        wd  = now.weekday()
        tot = now.hour * 60 + now.minute
        return wd < 5 and 15 * 60 + 30 <= tot < 22 * 60
    except Exception:
        return False   # fail-safe : on suppose fermé si tzdata absent


def evaluate_pending(days_back: int = 60) -> dict:
    """
    Évalue tous les conseils non évalués des `days_back` derniers jours.
    Requiert Supabase. Utilise yfinance pour les prix de clôture J+1.
    Skip les conseils dont le J+1 est aujourd'hui si le marché est encore ouvert
    (prix intraday non représentatif — le scheduler s'en chargera via evaluate_yesterday_advice).
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

                    j1_date = suivants.index[0].date()
                    # Si J+1 est aujourd'hui et le marché est encore ouvert :
                    # on skip — le prix intraday n'est pas la clôture finale.
                    if j1_date == today and _market_open_now():
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


def reset_intraday_evals() -> int:
    """
    Remet à NULL les évaluations faites HORS de la fenêtre 20h-22h Paris
    (prix d'ouverture ou intraday non représentatifs).
    Appelée avant evaluate_pending() dans la route admin/stats.
    Retourne le nombre de lignes invalidées.
    """
    try:
        import zoneinfo
        from db import _init, _client, is_available
        if not is_available():
            return 0
        _init()

        # Récupérer les évaluations récentes (7 derniers jours) ayant un evaluated_at
        rows = (
            _client.table("daily_advice")
            .select("id,evaluated_at")
            .not_.is_("bon_conseil", "null")
            .not_.is_("evaluated_at", "null")
            .gte("date_conseil", str(date.today() - timedelta(days=7)))
            .execute()
            .data or []
        )

        reset_count = 0
        paris_tz = zoneinfo.ZoneInfo("Europe/Paris")
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["evaluated_at"].replace("Z", "+00:00"))
                ts_paris = ts.astimezone(paris_tz)
                wd  = ts_paris.weekday()
                tot = ts_paris.hour * 60 + ts_paris.minute
                in_eval_window = wd < 5 and 20 * 60 <= tot < 22 * 60
                if not in_eval_window:
                    _client.table("daily_advice").update({
                        "bon_conseil":  None,
                        "prix_j1":      None,
                        "variation_j1": None,
                        "evaluated_at": None,
                    }).eq("id", row["id"]).execute()
                    reset_count += 1
            except Exception:
                pass

        if reset_count:
            print(f"[Evaluator] {reset_count} évaluation(s) hors-fenêtre invalidée(s)", flush=True)
        return reset_count

    except Exception as e:
        print(f"[Evaluator] reset_intraday_evals erreur : {e}", flush=True)
        return 0


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

    # Conseils explicitement suivis (position liée via conseil_date)
    followed_rows = (
        _client.table("positions")
        .select("ticker,conseil_date,type")
        .not_.is_("conseil_date", "null")
        .execute()
        .data or []
    )
    # Clés (ticker, conseil_date) des conseils suivis
    followed_keys = {(r["ticker"], r["conseil_date"]) for r in followed_rows}

    if not rows:
        return {"total": 0, "bons": 0, "mauvais": 0, "taux_pct": None,
                "by_action": {}, "by_ticker": [], "suivis": 0, "taux_suivi_pct": None}

    total   = len(rows)
    bons    = sum(1 for r in rows if r["bon_conseil"])
    mauvais = total - bons
    taux    = round(bons / total * 100, 1) if total else None

    # Conseils évalués ET suivis (intersection)
    suivis_evalues = [r for r in rows if (r["ticker"], r["date_conseil"]) in followed_keys]
    nb_suivis      = len(followed_keys)
    nb_bons_suivis = sum(1 for r in suivis_evalues if r["bon_conseil"])
    taux_suivi     = round(nb_bons_suivis / len(suivis_evalues) * 100, 1) if suivis_evalues else None

    # ── Par action ──
    action_stats: dict[str, dict] = {}
    for r in rows:
        a = r.get("action", "?")
        s = action_stats.setdefault(a, {"total": 0, "bons": 0, "suivis": 0})
        s["total"] += 1
        if r["bon_conseil"]:
            s["bons"] += 1
        if (r["ticker"], r["date_conseil"]) in followed_keys:
            s["suivis"] += 1
    for a, s in action_stats.items():
        s["taux_pct"] = round(s["bons"] / s["total"] * 100, 1) if s["total"] else None

    # ── Par ticker ──
    ticker_stats: dict[str, dict] = {}
    for r in rows:
        t = r["ticker"]
        s = ticker_stats.setdefault(t, {"ticker": t, "total": 0, "bons": 0,
                                        "suivis": 0, "last_date": "", "last_action": ""})
        s["total"] += 1
        if r["bon_conseil"]:
            s["bons"] += 1
        if (r["ticker"], r["date_conseil"]) in followed_keys:
            s["suivis"] += 1
        if r["date_conseil"] > s["last_date"]:
            s["last_date"]   = r["date_conseil"]
            s["last_action"] = r["action"]

    for s in ticker_stats.values():
        s["taux_pct"] = round(s["bons"] / s["total"] * 100, 1) if s["total"] else None

    ticker_list = sorted(ticker_stats.values(), key=lambda x: -x["total"])

    return {
        "total":           total,
        "bons":            bons,
        "mauvais":         mauvais,
        "taux_pct":        taux,
        "suivis":          nb_suivis,
        "bons_suivis":     nb_bons_suivis,
        "taux_suivi_pct":  taux_suivi,
        "by_action":       action_stats,
        "by_ticker": ticker_list,
    }
