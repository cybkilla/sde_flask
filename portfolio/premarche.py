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


def _donnees_brutes(t: str) -> tuple:
    """
    (prix_premarche, clot_veille, gap_pct, confirme) pour un ticker.

    confirme=True : get_premarket_gap() a réussi (yfinance) — prix
    pré-marché ET clôture veille viennent de la MÊME source, gap_pct =
    vrai gap pré-marché.

    confirme=False : repli get_live_price() (Finnhub), hors séance.
    ERREUR CORRIGÉE le 31.07.2026 (signalée par l'utilisateur, décalage
    d'un jour repéré à l'œil) : Finnhub hors séance fige son "prix actuel"
    (c) sur la clôture RÉELLE de la veille (J-1) — PAS un prix pré-marché
    — et son "prev_close" (pc) est alors la clôture d'AVANT (J-2), pas
    "la veille". Vérifié en réel sur ITG : timestamp du quote = clôture
    du 30.07 (J-1), pc = clôture du 29.07 (J-2). On affiche donc live["price"]
    comme clôture veille (c'est ce qu'il EST réellement), jamais comme
    "prix pré-marché" — et aucun prix pré-marché n'est renvoyé dans ce
    cas (on n'en a pas), donc pas de gap calculable non plus (calculer un
    % entre J-1 et J-2 serait exactement l'ancien bug : la variation de
    la veille, pas un gap pré-marché).
    """
    from data.market import get_premarket_gap, get_live_price
    pm = get_premarket_gap(t)
    if pm:
        return pm["prix"], pm["prev_close"], pm["gap_pct"], True
    live = get_live_price(t) or {}
    return None, live.get("price"), None, False


def etat_premarche(username: str) -> list[dict]:
    """
    Pour chaque position OUVERTE : vrai gap pré-marché (data.market.
    get_premarket_gap — PAS get_live_price()["var_1d"], qui reste figé
    sur la clôture de la veille hors séance sur les sources gratuites,
    cf. son docstring), et si ce gap est notable au sens de
    gap_significatif() (seuil adapté à l'ATR du titre — même règle que
    la réévaluation de conseil). Trié par |gap| décroissant (les tickers
    sans donnée, gap_pct=None, se retrouvent en fin de liste).

    Un ticker sans vrai prix pré-marché (le cas le plus fréquent en prod
    — yfinance, seule source à l'avoir, est bloqué depuis Render) reste
    dans le résultat avec sa clôture de la veille (correcte, cf.
    _donnees_brutes) mais `prix=None`, `gap_pct=None` — jamais de prix
    pré-marché ni de gap inventés. Le prix utilisé pour le P&L retombe
    alors sur la clôture veille, seule valeur fiable disponible.

    Récupération EN PARALLÈLE (pas séquentielle) : chaque appel réseau
    peut prendre jusqu'à 8-12s (timeout yfinance, ou Finnhub ralenti) —
    en séquence sur N positions, ça bloquait le SEUL worker gunicorn
    (sync, mono-worker) jusqu'à N fois ce délai, gelant AUSSI
    /portfolio/overview et le reste du site pendant ce temps (vécu
    31.07.2026 : "Chargement des positions" resté bloqué). Même
    raisonnement que pipeline.py pour les mêmes raisons.
    """
    import concurrent.futures
    from portfolio.positions import get_positions, get_portfolio_summary
    from portfolio.risk import gap_significatif, atr_pct
    from snapshot import get_snapshot, MAX_AGE_HOURS

    lots = get_positions(username)
    tickers = list(dict.fromkeys(l["ticker"] for l in lots))
    if not tickers:
        return []

    donnees = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tickers)) as ex:
        futs = {ex.submit(_donnees_brutes, t): t for t in tickers}
        for fut in concurrent.futures.as_completed(futs):
            t = futs[fut]
            try:
                donnees[t] = fut.result()
            except Exception as e:
                print(f"[Premarche] {t} ignoré : {e}", flush=True)

    etats = []
    for t in tickers:
        try:
            prix, prev_close, gap, confirme = donnees.get(t, (None, None, None, False))
            prix_ref = prix if prix is not None else prev_close   # meilleur prix connu pour le P&L
            if prix_ref is None:
                continue   # aucune donnée du tout, même de secours -> rien à montrer
            s = get_portfolio_summary(username, t, prix_ref)
            if not s or s.get("position_fermee"):
                continue
            snap = get_snapshot(t, max_age_hours=MAX_AGE_HOURS)
            atr  = atr_pct((snap or {}).get("market", {}).get("history")) if snap else None
            company = next((l["company"] for l in lots
                            if l["ticker"] == t and l.get("company")), t)
            etats.append({
                "ticker":     t,
                "company":    company,
                "prix":       prix,
                "prev_close": prev_close,
                "gap_pct":    gap,
                "confirme":   confirme,
                "notable":    gap_significatif(gap, atr) if (confirme and gap is not None) else False,
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
