# analysis/opportunites_evaluator.py — évaluation multi-horizons du Top 5
# opportunités court terme (même esprit que portfolio/evaluator.py pour
# daily_advice, mais nettement plus simple).
#
# Pourquoi ce module : le Top 5 n'était jamais confronté à la réalité après
# coup — on jugeait ticker par ticker "à l'œil" (ex. discussion TMC/FCEL du
# 24.07.2026) sans savoir si l'outil repère vraiment de bonnes opportunités
# sur la durée. Chaque scan sauvegarde désormais son Top 5, et ce module
# vérifie ensuite ce qui s'est réellement passé.
#
# Différence clé avec daily_advice : un conseil peut être ACHETER, TENIR ou
# VENDRE (jugement asymétrique selon l'action). Le Top 5, lui, est TOUJOURS
# un pari implicite à la hausse — c'est tout l'intérêt du scan (repérer où
# déployer du cash). Le jugement est donc simplement : le prix a-t-il monté ?
# Horizons identiques à daily_advice (J+1/J+5/J+20) pour rester comparable,
# et pour la même raison : le J+1 seul ne mesure que le bruit du jour.

from datetime import date, datetime, timezone, timedelta
from collections import defaultdict

HORIZONS = (1, 5, 20)
_TABLE   = "opportunites_historique"


def enregistrer_resultats(resultats: list[dict], date_scan: str = None):
    """
    Sauvegarde chaque ligne du Top 5 d'un scan pour évaluation future.
    Appelé depuis screener.lancer_scan() juste après le tri final —
    silencieux si Supabase indisponible (même contrat que
    screener._persister_resultats).
    """
    try:
        from db import insert_one, is_available
        if not is_available() or not resultats:
            return
        jour = date_scan or date.today().isoformat()
        for r in resultats:
            if not r.get("prix"):
                continue   # pas de prix d'entrée -> rien à évaluer plus tard
            insert_one(_TABLE, {
                "ticker":         r["ticker"],
                "company_name":   r.get("company_name"),
                "date_scan":      jour,
                "score_global":   r.get("score_global"),
                "recommandation": r.get("recommandation"),
                "prix_scan":      r["prix"],
                "rsi":            r.get("rsi"),
                "var_5d":         r.get("var_5d"),
            })
    except Exception as e:
        print(f"[OpportunitesEvaluator] enregistrement échoué : {e}", flush=True)


def _juger_horizons(prix_scan: float, closes: list[float], deja: dict) -> dict:
    """
    Calcule les colonnes à mettre à jour pour chaque horizon pas encore
    évalué, à partir des clôtures RÉELLEMENT disponibles après le scan
    (`closes[0]` = J+1, `closes[4]` = J+5, etc.). Fonction PURE — testable
    sans réseau ni DataFrame, juste une liste de flottants.
    """
    update = {}
    for h in HORIZONS:
        if deja.get(h) or len(closes) < h:
            continue   # déjà évalué, ou pas encore assez de séances écoulées
        prix_h    = closes[h - 1]
        variation = round((prix_h - prix_scan) / prix_scan * 100, 2)
        update[f"prix_j{h}"]      = round(prix_h, 4)
        update[f"variation_j{h}"] = variation
        update[f"bon_j{h}"]       = variation > 0
    return update


def evaluate_pending(days_back: int = 60) -> dict:
    """
    Complète les évaluations manquantes (J+1/J+5/J+20) des scans des
    `days_back` derniers jours. Requiert Supabase, historique de prix via
    portfolio.evaluator._fetch_eval_history (yfinance -> Twelve Data).
    """
    import db
    from db import _init, is_available
    if not is_available():
        return {"evaluated": 0, "skipped": 0, "errors": 0}

    _init()
    today  = date.today()
    cutoff = str(today - timedelta(days=days_back))

    # Table absente si la migration SQL n'a pas encore été appliquée
    # (doc/SUPABASE.md) — dégradation silencieuse, comme partout ailleurs
    # dans le projet quand une migration manque (cf. check_supabase_schema.py).
    try:
        rows = (
            db._client.table(_TABLE)
            .select("id,ticker,date_scan,prix_scan,bon_j1,bon_j5,bon_j20")
            .or_("bon_j1.is.null,bon_j5.is.null,bon_j20.is.null")
            .gte("date_scan", cutoff)
            .lt("date_scan", str(today))
            .execute()
            .data or []
        )
    except Exception as e:
        print(f"[OpportunitesEvaluator] table indisponible (migration manquante ?) : {e}", flush=True)
        return {"evaluated": 0, "skipped": 0, "errors": 0}
    if not rows:
        return {"evaluated": 0, "skipped": 0, "errors": 0}

    by_ticker = defaultdict(list)
    for row in rows:
        if row.get("prix_scan"):
            by_ticker[row["ticker"]].append(row)

    evaluated = skipped = errors = 0

    from portfolio.evaluator import _fetch_eval_history, _market_open_now
    marche_ouvert = _market_open_now()

    for ticker, ticker_rows in by_ticker.items():
        try:
            min_date = min(r["date_scan"] for r in ticker_rows)
            depart   = str(datetime.strptime(min_date, "%Y-%m-%d").date() - timedelta(days=5))
            hist = _fetch_eval_history(ticker, depart, today)
            if hist.empty:
                skipped += len(ticker_rows)
                continue

            for row in ticker_rows:
                try:
                    d_scan   = datetime.strptime(row["date_scan"], "%Y-%m-%d")
                    suivants = hist[hist.index > d_scan]
                    prix_j0  = float(row["prix_scan"])
                    if suivants.empty or prix_j0 == 0:
                        skipped += 1
                        continue

                    deja = {1: row.get("bon_j1") is not None,
                            5: row.get("bon_j5") is not None,
                            20: row.get("bon_j20") is not None}

                    # Ne garde que les clôtures d'un jour déjà terminé —
                    # la bougie du jour même n'est pas finale si le marché tourne.
                    closes = [
                        float(suivants.iloc[i]["Close"])
                        for i in range(len(suivants))
                        if not (suivants.index[i].date() == today and marche_ouvert)
                    ]

                    update = _juger_horizons(prix_j0, closes, deja)
                    if not update:
                        skipped += 1
                        continue

                    update["evaluated_at"] = datetime.now(timezone.utc).isoformat()
                    db._client.table(_TABLE).update(update).eq("id", row["id"]).execute()
                    evaluated += 1
                    print(f"[OpportunitesEvaluator] {ticker} {row['date_scan']} "
                          f"maj {list(update.keys())}", flush=True)
                except Exception as re:
                    print(f"[OpportunitesEvaluator] {ticker} ligne erreur : {re}", flush=True)
                    errors += 1
        except Exception as te:
            print(f"[OpportunitesEvaluator] {ticker} historique erreur : {te}", flush=True)
            errors += len(ticker_rows)

    return {"evaluated": evaluated, "skipped": skipped, "errors": errors}


def get_stats() -> dict:
    """Taux de réussite et gain moyen par horizon, sur tout l'historique évalué."""
    import db
    from db import _init, is_available
    if not is_available():
        return {}
    _init()
    try:
        rows = (
            db._client.table(_TABLE)
            .select("bon_j1,bon_j5,bon_j20,variation_j20")
            .execute()
            .data or []
        )
    except Exception as e:
        print(f"[OpportunitesEvaluator] table indisponible (migration manquante ?) : {e}", flush=True)
        return {"total": 0}
    if not rows:
        return {"total": 0}

    def _horizon(key_bon):
        ev   = [r for r in rows if r.get(key_bon) is not None]
        taux = round(sum(1 for r in ev if r[key_bon]) / len(ev) * 100, 1) if ev else None
        return {"evalues": len(ev), "taux_pct": taux}

    gains = [r["variation_j20"] for r in rows if r.get("variation_j20") is not None]

    return {
        "total":          len(rows),
        "j1":             _horizon("bon_j1"),
        "j5":             _horizon("bon_j5"),
        "j20":            _horizon("bon_j20"),
        "gain_j20_moyen": round(sum(gains) / len(gains), 2) if gains else None,
    }
