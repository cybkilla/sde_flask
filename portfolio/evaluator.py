# portfolio/evaluator.py — Évaluation automatique des conseils passés
#
# Multi-horizons : un conseil s'appuie sur des signaux moyen terme (14-50j),
# le juger sur la seule bougie du lendemain (±1.5% de bruit quotidien)
# revient à mesurer du hasard. On évalue donc à TROIS horizons :
#   J+1  : réactivité immédiate (conservé pour l'existant)
#   J+5  : la semaine qui suit
#   J+20 : l'horizon aligné sur les signaux — c'est LUI qui fait foi
# Chaque ligne daily_advice se remplit progressivement au fil des passages
# du scheduler (J+5 n'est observable que 5 séances après le conseil).

from datetime import date, datetime, timezone, timedelta
from collections import defaultdict

# Les horizons évalués (en jours de BOURSE, pas calendaires)
HORIZONS = (1, 5, 20)


def _seuil_tenir(h: int) -> float:
    """
    Tolérance du "bon TENIR" selon l'horizon. Un cours diffuse comme √temps
    (marche aléatoire) : la bande de ±3% acceptable à J+1 doit s'élargir en
    √h — sinon quasi aucun TENIR ne serait "bon" à J+20.
    J+1 → ±3%, J+5 → ±6.7%, J+20 → ±13.4%.
    """
    return round(3.0 * h ** 0.5, 1)


def _juger(action: str, variation: float, horizon: int):
    """
    Le conseil était-il bon, vu la variation constatée à cet horizon ?
    Fonction PURE (testable hors réseau). None = action non jugeable.
    """
    if action in ("ACHETER", "RENFORCER"):
        return variation > 0
    if action in ("VENDRE", "ALLÉGER"):
        return variation < 0
    if action in ("TENIR", "SURVEILLER"):
        return abs(variation) < _seuil_tenir(horizon)
    return None


def _gain(action: str, variation: float):
    """
    Gain (ou coût) RÉEL du conseil en % signé — bien plus informatif que
    le binaire bon/mauvais : un VENDRE qui a raté +15% et un VENDRE qui a
    raté +0.3% ne se valent pas.
      ACHETER/RENFORCER : on profite de la hausse  → gain = +variation
      VENDRE/ALLÉGER    : on évite la baisse       → gain = -variation
      TENIR/SURVEILLER  : pas de pari directionnel → None
    """
    if action in ("ACHETER", "RENFORCER"):
        return round(variation, 2)
    if action in ("VENDRE", "ALLÉGER"):
        return round(-variation, 2)
    return None


def _fetch_eval_history(ticker: str, start_date: str, today: date):
    """
    Historique de clôtures pour l'évaluation : yfinance d'abord, puis
    Twelve Data — même stratégie que market.py et backtest.py, car
    yfinance est rate-limité sur Render et le scheduler y appelle
    désormais l'évaluateur à chaque passage.
    Retourne un DataFrame (possiblement vide) avec index dates naïves.
    """
    import pandas as pd
    hist = pd.DataFrame()
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(
            start=start_date,
            end=str(today + timedelta(days=1)),
            auto_adjust=True,
        )
    except Exception as e:
        print(f"[Evaluator] yfinance erreur ({ticker}) : {e}", flush=True)

    if hist is None or hist.empty:
        # outputsize Twelve Data = jours de BOURSE ; on convertit les jours
        # calendaires écoulés (~5/7) avec une marge, borné à 5000
        try:
            from data.market import _get_candles_td
            jours_cal = (today - datetime.strptime(start_date, "%Y-%m-%d").date()).days
            outputsize = min(max(30, int(jours_cal * 0.75) + 10), 5000)
            print(f"[Evaluator] fallback Twelve Data pour {ticker}", flush=True)
            hist = _get_candles_td(ticker, outputsize)
        except Exception as e:
            print(f"[Evaluator] fallback TD erreur ({ticker}) : {e}", flush=True)
            hist = pd.DataFrame()

    if hist is not None and not hist.empty:
        if hist.index.tz is not None:
            hist.index = hist.index.tz_convert(None)
        hist.index = hist.index.normalize()
    return hist


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
    Complète les évaluations manquantes (J+1, J+5, J+20) des conseils des
    `days_back` derniers jours. Chaque ligne se remplit progressivement :
    à J+3 seul le J+1 est observable, à J+25 les trois horizons le sont.
    Requiert Supabase, prix de clôture via yfinance.
    Retourne {"evaluated": int, "skipped": int, "errors": int} —
    evaluated compte les LIGNES ayant reçu au moins un nouvel horizon.
    """
    import db
    from db import _init, is_available
    if not is_available():
        return {"evaluated": 0, "skipped": 0, "errors": 0}

    _init()
    today   = date.today()
    cutoff  = str(today - timedelta(days=days_back))

    # Lignes où AU MOINS un horizon manque encore.
    # .or_ : syntaxe PostgREST "colonne.is.null" séparée par des virgules.
    rows = (
        db._client.table("daily_advice")
        .select("id,username,ticker,date_conseil,action,prix_jour,"
                "bon_conseil,bon_conseil_j5,bon_conseil_j20")
        .or_("bon_conseil.is.null,bon_conseil_j5.is.null,bon_conseil_j20.is.null")
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
    marche_ouvert = _market_open_now()

    for ticker, ticker_rows in by_ticker.items():
        try:
            min_date = min(r["date_conseil"] for r in ticker_rows)
            # yfinance → fallback Twelve Data (index déjà normalisé)
            hist = _fetch_eval_history(ticker, min_date, today)
            if hist.empty:
                skipped += len(ticker_rows)
                continue

            for row in ticker_rows:
                try:
                    d_conseil = datetime.strptime(row["date_conseil"], "%Y-%m-%d")
                    suivants  = hist[hist.index > d_conseil]
                    prix_j0   = float(row["prix_jour"])
                    action    = row.get("action", "")
                    if suivants.empty or prix_j0 == 0:
                        skipped += 1
                        continue

                    # Colonne déjà remplie ? (clé Supabase par horizon)
                    deja = {1: row.get("bon_conseil")     is not None,
                            5: row.get("bon_conseil_j5")  is not None,
                            20: row.get("bon_conseil_j20") is not None}
                    suffixe = {1: "j1", 5: "j5", 20: "j20"}

                    update = {}
                    for h in HORIZONS:
                        if deja[h] or len(suivants) < h:
                            continue          # déjà fait, ou pas assez de séances
                        h_date = suivants.index[h - 1].date()
                        # Clôture du jour même pas encore finale si marché ouvert
                        if h_date == today and marche_ouvert:
                            continue
                        prix_h    = float(suivants.iloc[h - 1]["Close"])
                        variation = round((prix_h - prix_j0) / prix_j0 * 100, 2)
                        bon       = _juger(action, variation, h)
                        if bon is None:
                            continue          # action inconnue → pas jugeable
                        s = suffixe[h]
                        update[f"prix_{s}"]      = round(prix_h, 4)
                        update[f"variation_{s}"] = variation
                        # Historique : la colonne J+1 s'appelle bon_conseil
                        update["bon_conseil" if h == 1 else f"bon_conseil_{s}"] = bon
                        if h == 20:
                            g = _gain(action, variation)
                            if g is not None:
                                update["gain_j20_pct"] = g

                    if not update:
                        skipped += 1
                        continue

                    update["evaluated_at"] = datetime.now(timezone.utc).isoformat()
                    try:
                        db._client.table("daily_advice").update(update) \
                               .eq("id", row["id"]).execute()
                    except Exception:
                        # Migration SQL pas encore appliquée → on sauve au
                        # moins le J+1 (colonnes historiques) plutôt que rien
                        j1_only = {k: v for k, v in update.items()
                                   if k in ("prix_j1", "variation_j1",
                                            "bon_conseil", "evaluated_at")}
                        if j1_only.get("bon_conseil") is None:
                            raise
                        db._client.table("daily_advice").update(j1_only) \
                               .eq("id", row["id"]).execute()
                        print("[Evaluator] colonnes J+5/J+20 absentes — lancer "
                              "la migration SQL (voir doc/SUPABASE.md)", flush=True)

                    evaluated += 1
                    detail = " ".join(
                        f"J+{h}:{'✓' if update.get('bon_conseil' if h == 1 else f'bon_conseil_j{h}') else '✗'}"
                        for h in HORIZONS
                        if ("bon_conseil" if h == 1 else f"bon_conseil_j{h}") in update
                    )
                    print(f"[Evaluator] {ticker} {row['date_conseil']} {action} {detail}",
                          flush=True)

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
        import db
        from db import _init, is_available
        if not is_available():
            return 0
        _init()

        # Récupérer les évaluations récentes (7 derniers jours) ayant un evaluated_at
        rows = (
            db._client.table("daily_advice")
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
                    db._client.table("daily_advice").update({
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
    import db
    from db import _init, is_available
    if not is_available():
        return {}

    _init()
    try:
        rows = (
            db._client.table("daily_advice")
            .select("ticker,action,bon_conseil,variation_j1,date_conseil,username,"
                    "bon_conseil_j5,bon_conseil_j20,gain_j20_pct")
            .not_.is_("bon_conseil", "null")
            .execute()
            .data or []
        )
    except Exception:
        # Colonnes J+5/J+20 absentes (migration non appliquée) → mode J+1 seul
        rows = (
            db._client.table("daily_advice")
            .select("ticker,action,bon_conseil,variation_j1,date_conseil,username")
            .not_.is_("bon_conseil", "null")
            .execute()
            .data or []
        )

    # Conseils explicitement suivis (position liée via conseil_date)
    followed_rows = (
        db._client.table("positions")
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

    # ── Horizons J+5 / J+20 : le taux qui fait foi est le J+20 ──
    # (les conseils s'appuient sur des signaux 14-50j — le J+1 mesure
    # surtout le bruit quotidien)
    ev_j5     = [r for r in rows if r.get("bon_conseil_j5")  is not None]
    ev_j20    = [r for r in rows if r.get("bon_conseil_j20") is not None]
    taux_j5   = round(sum(1 for r in ev_j5  if r["bon_conseil_j5"])  / len(ev_j5)  * 100, 1) if ev_j5  else None
    taux_j20  = round(sum(1 for r in ev_j20 if r["bon_conseil_j20"]) / len(ev_j20) * 100, 1) if ev_j20 else None
    # Gain moyen réel des conseils directionnels à J+20 (% signé)
    gains     = [r["gain_j20_pct"] for r in rows if r.get("gain_j20_pct") is not None]
    gain_j20  = round(sum(gains) / len(gains), 2) if gains else None

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
        "by_ticker":       ticker_list,
        # Multi-horizons
        "evalues_j5":      len(ev_j5),
        "taux_j5_pct":     taux_j5,
        "evalues_j20":     len(ev_j20),
        "taux_j20_pct":    taux_j20,
        "gain_j20_moyen":  gain_j20,
    }
