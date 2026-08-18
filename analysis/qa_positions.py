# analysis/qa_positions.py — Q&A scopée sur UN ticker ou LE portefeuille de
# l'utilisateur (positions + watchlist) — jamais sur autre chose.
#
# Idée du 18.08.2026 : les questions "je sors de FCEL pour renforcer TMC ?"
# posées en session de dev n'étaient pas du code — de l'analyse de données
# que SDE peut faire lui-même, avec les mêmes fonctions déjà utilisées par
# le conseil quotidien et le badge de fiabilité. Portée volontairement
# restreinte à un choix explicite (1 ticker dans un menu, ou "tout le
# portefeuille") plutôt que du texte libre + détection de ticker — plus
# simple à garantir : le backend ne charge JAMAIS de données hors de ce
# qui a été explicitement choisi, la question du LLM qui "sortirait du
# cadre" ne se pose donc que pour du bruit hors-sujet, pas pour une fuite
# de portée.

import requests
from config import (
    GROQ_API_KEY, GROQ_MODEL, LLM_ENABLED,
    QA_MAX_TOKENS, QA_REASONING_EFFORT, QA_TIMEOUT,
)

REFUS = ("Cette question sort du cadre de tes positions suivies par SDE — "
         "je ne peux répondre qu'à propos du ticker ou du portefeuille "
         "sélectionné, avec les données que SDE a sur eux.")

QUESTION_MAX_LEN = 500


def tickers_disponibles(username: str) -> list[str]:
    """Tickers autorisés pour cet utilisateur (positions + watchlist,
    dédupliqués, triés) — la SEULE source de vérité de la portée, utilisée
    à la fois pour peupler le menu et pour valider le ticker choisi."""
    from portfolio.positions import get_positions
    from watchlist.watchlist import get_watchlist
    pos = {l["ticker"] for l in (get_positions(username) or []) if l.get("ticker")}
    wl  = {w["ticker"] for w in (get_watchlist(username) or []) if w.get("ticker")}
    return sorted(pos | wl)


def _bloc_ticker(username: str, ticker: str) -> str | None:
    """Bloc de contexte texte pour UN ticker — None si SDE n'a strictement
    aucune donnée dessus (ni prix, ni position, ni conseil)."""
    from data.market import get_live_price, get_next_earnings
    from portfolio.positions import get_positions, get_portfolio_summary
    from portfolio.advisor import get_today_advice, get_advice_history
    from portfolio.evaluator import get_ticker_stats_bulk

    live  = get_live_price(ticker) or {}
    price = live.get("price")
    summary = get_portfolio_summary(username, ticker, price or 0)

    advice = get_today_advice(username, ticker)
    if not advice:
        hist = get_advice_history(username, ticker, limit=1)
        advice = hist[0] if hist else None

    stats    = get_ticker_stats_bulk(username, [ticker]).get(ticker)
    earnings = get_next_earnings(ticker)

    if price is None and summary is None and advice is None:
        return None

    lots    = get_positions(username, ticker) or []
    company = next((l["company"] for l in lots if l.get("company")), ticker)

    lignes = [f"### {ticker} ({company})"]
    if price is not None:
        var = live.get("var_1d")
        var_txt = f" ({var:+.2f}% aujourd'hui)" if var is not None else ""
        lignes.append(f"Prix actuel : {price}${var_txt}")

    if summary and not summary.get("position_fermee"):
        ppp = summary.get("pnl_position_pct")
        ppp_txt = f"{ppp:+.1f}%" if ppp is not None else "inconnu"
        lignes.append(
            f"Position détenue : {summary['total_shares']:g} actions, coût "
            f"moyen {summary['cout_moyen']:.2f}$, P&L de la position {ppp_txt}."
        )
    elif summary and summary.get("position_fermee"):
        lignes.append("Position clôturée (plus aucune action détenue actuellement).")
    else:
        lignes.append("Pas de position détenue — suivi en watchlist uniquement.")

    if advice:
        lignes.append(
            f"Conseil SDE du {advice.get('date_conseil')} : "
            f"{advice.get('action')} (score {advice.get('score_sde')}/100). "
            f"Raisonnement : {advice.get('raisonnement', '')}"
        )
    else:
        lignes.append("Aucun conseil SDE généré pour l'instant sur ce titre.")

    if stats and stats.get("total", 0) >= 3:
        lignes.append(
            f"Fiabilité mesurée sur ce titre (taux de bons conseils à J+1) : "
            f"{stats['taux_pct']}% sur {stats['total']} conseils évalués."
        )

    if earnings:
        if earnings.get("statut") == "publie":
            vs = (f" vs {earnings['eps_estimate']}$ attendu"
                  if earnings.get("eps_estimate") is not None else "")
            lignes.append(
                f"Résultats trimestriels publiés le {earnings['date']} : "
                f"BPA {earnings.get('eps_actual')}${vs}."
            )
        else:
            lignes.append(
                f"Résultats trimestriels attendus le {earnings['date']} "
                f"(dans {earnings['jours']} jours)."
            )

    return "\n".join(lignes)


def _contexte(username: str, scope: str, ticker: str | None) -> tuple[str | None, str | None]:
    """Retourne (contexte, erreur) — l'un des deux est toujours None."""
    autorises = tickers_disponibles(username)

    if scope == "ticker":
        ticker = (ticker or "").upper()
        if not ticker or ticker not in autorises:
            return None, "Ce ticker n'est ni dans tes positions ni dans ta watchlist."
        bloc = _bloc_ticker(username, ticker)
        if not bloc:
            return None, "Aucune donnée disponible sur ce ticker pour l'instant."
        return bloc, None

    if scope == "portefeuille":
        from portfolio.positions import get_positions, get_portfolio_summary
        tickers_lots = sorted({l["ticker"] for l in (get_positions(username) or [])
                               if l.get("ticker")})
        detenus = []
        for t in tickers_lots:
            s = get_portfolio_summary(username, t, 0)   # prix=0 : juste pour tester position_fermee
            if s and not s.get("position_fermee"):
                detenus.append(t)
        if not detenus:
            return None, "Aucune position détenue pour l'instant."
        blocs = []
        for t in detenus:
            bloc = _bloc_ticker(username, t)
            if bloc:
                blocs.append(bloc)
        if not blocs:
            return None, "Aucune donnée disponible sur les positions détenues."
        return "\n\n".join(blocs), None

    return None, "Portée inconnue."


def ask(username: str, scope: str, ticker: str | None, question: str) -> dict:
    """
    Répond à une question sur `scope` ("ticker" ou "portefeuille"). Ne lève
    jamais d'exception — dégradation propre à chaque étape avec un message
    d'erreur explicite. Retourne {"ok": True, "reponse": str} ou
    {"ok": False, "error": str}.
    """
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error": "Question vide."}
    if len(question) > QUESTION_MAX_LEN:
        return {"ok": False, "error": f"Question trop longue ({QUESTION_MAX_LEN} caractères max)."}

    if not LLM_ENABLED:
        return {"ok": False, "error": "Fonctionnalité IA désactivée."}
    if not GROQ_API_KEY:
        return {"ok": False, "error": "Fonctionnalité indisponible (clé Groq absente)."}

    contexte, err = _contexte(username, scope, ticker)
    if err:
        return {"ok": False, "error": err}

    system = (
        "Tu es un analyste qui répond UNIQUEMENT à des questions sur les "
        "titres décrits dans le CONTEXTE ci-dessous — jamais sur d'autres "
        "titres, jamais sur des sujets de marché ou d'économie générale, "
        "jamais depuis tes connaissances générales sur ces entreprises. "
        f"Si la question sort de ce cadre, réponds EXACTEMENT ceci et rien "
        f"d'autre : \"{REFUS}\"\n\n"
        "Sinon, réponds en français, 5 à 8 phrases maximum, de façon "
        "factuelle en t'appuyant sur le contexte fourni. Ne donne jamais "
        "un ordre impératif (\"vends\", \"achète\") — présente les faits "
        "et les compromis, la décision reste à l'utilisateur, dans le même "
        "esprit que les conseils SDE. N'invente aucune donnée absente du "
        "contexte.\n\n"
        f"CONTEXTE :\n{contexte}"
    )

    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "reasoning_effort": QA_REASONING_EFFORT,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "max_tokens":  QA_MAX_TOKENS,
            "temperature": 0.3,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload, timeout=QA_TIMEOUT,
        )
        resp.raise_for_status()
        texte = resp.json()["choices"][0]["message"]["content"].strip()
        return {"ok": True, "reponse": texte}
    except Exception as e:
        print(f"[QA] échec (scope={scope}, ticker={ticker}) : {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "error": "Le service IA est temporairement indisponible."}
