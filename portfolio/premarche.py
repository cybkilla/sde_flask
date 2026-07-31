# portfolio/premarche.py — état pré-marché des positions ouvertes
#
# Demandé le 31.07.2026 : "se préparer à ce qui va arriver au cours de la
# séance à venir" — distinct des alertes existantes (qui ne se
# déclenchent que si un gap overnight change le conseil du jour, cf.
# alerts/scheduler.py::_check_position_advice) : ici on veut TOUJOURS
# voir l'état des positions avant l'ouverture, notable ou pas, dans
# "Mes positions" — et en plus un email, mais seulement s'il y a au
# moins un mouvement notable (pas un digest systématique tous les jours,
# pour ne pas retomber dans le problème de volume d'emails du 28.07.2026).

from datetime import date


def etat_premarche(username: str) -> list[dict]:
    """
    Pour chaque position OUVERTE : vrai gap pré-marché (data.market.
    get_premarket_gap — PAS get_live_price()["var_1d"], qui reste figé
    sur la clôture de la veille hors séance sur les sources gratuites,
    cf. son docstring), et si ce gap est notable au sens de
    gap_significatif() (seuil adapté à l'ATR du titre — même règle que
    la réévaluation de conseil). Trié par |gap| décroissant.

    Un ticker sans donnée pré-marché disponible (le cas le plus fréquent
    en prod — yfinance, seule source à l'avoir, est bloqué depuis Render)
    est simplement absent du résultat plutôt que d'afficher un gap faux.
    """
    from portfolio.positions import get_positions, get_portfolio_summary
    from data.market import get_premarket_gap
    from portfolio.risk import gap_significatif, atr_pct
    from snapshot import get_snapshot, MAX_AGE_HOURS

    lots = get_positions(username)
    tickers = list(dict.fromkeys(l["ticker"] for l in lots))

    etats = []
    for t in tickers:
        try:
            pm = get_premarket_gap(t)
            if not pm:
                continue   # pas de donnée pré-marché disponible pour ce titre
            s = get_portfolio_summary(username, t, pm["prix"])
            if not s or s.get("position_fermee"):
                continue
            snap = get_snapshot(t, max_age_hours=MAX_AGE_HOURS)
            atr  = atr_pct((snap or {}).get("market", {}).get("history")) if snap else None
            company = next((l["company"] for l in lots
                            if l["ticker"] == t and l.get("company")), t)
            etats.append({
                "ticker":     t,
                "company":    company,
                "prix":       pm["prix"],
                "prev_close": pm["prev_close"],
                "gap_pct":    pm["gap_pct"],
                "notable":    gap_significatif(pm["gap_pct"], atr),
                "pnl_pct":    s["pnl_pct"],
            })
        except Exception as e:
            print(f"[Premarche] {t} ignoré : {e}", flush=True)

    etats.sort(key=lambda e: abs(e["gap_pct"] or 0), reverse=True)
    return etats


# ── Anti-spam de l'email digest : au plus 1×/jour/utilisateur ──────────
# Colonne sur `users` (attribut scalaire par utilisateur, pas un
# historique) — même choix de conception que cash_ajustement (28.07.2026).

def deja_envoye_aujourdhui(username: str) -> bool:
    try:
        from db import find_one, is_available
        if not is_available():
            return False
        row = find_one("users", {"username": username})
        return bool(row and str(row.get("premarche_digest_date")) == str(date.today()))
    except Exception as e:
        print(f"[Premarche] lecture date digest échouée : {e}", flush=True)
        return False


def marquer_envoye(username: str):
    try:
        from db import update_one, is_available
        if not is_available():
            return
        update_one("users", {"username": username},
                   {"$set": {"premarche_digest_date": str(date.today())}})
    except Exception as e:
        print(f"[Premarche] marquage date digest échoué : {e}", flush=True)
