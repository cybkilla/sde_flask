# pipeline.py
# Orchestre l'ensemble des modules dans l'ordre correct.
# Point d'entrée unique appelé par app.py (Streamlit).

import pandas as pd
import numpy  as np
from data.market          import get_market_data
from data.news            import get_all_news, get_sector_news
from data.insider         import (
    get_insider_transactions,
    get_executive_events,
    get_insider_score,
)
from analysis.scoring     import score_technique, score_fondamental, score_global, recommandation
from analysis.sentiment   import analyze_sentiment
from analysis.media_score    import compute_media_score
from analysis.executive_risk import compute_executive_risk_score
from analysis.llm_explain import generate_explanation, _fallback_text
from cache                import get_cached, set_cached
from config               import WEIGHT_TECH, WEIGHT_FUND, WEIGHT_MEDIA, LLM_ENABLED


def run(ticker: str, use_cache: bool = True) -> dict:
    """
    Pipeline principal — appel unique depuis l'interface.

    Étapes :
      1. Données marché       (yfinance → DataFrame Pandas)
      2. Actualités + sentiment (RSS/NewsAPI → DataFrame annoté)
      3. Insider + événements dirigeants (DataFrame)
      4. Score technique, fondamental, médiatique
      5. Agrégation pondérée → recommandation finale
      6. Génération explication LLM (Groq → Ollama → fallback)

    Paramètres
    ----------
    ticker    : symbole boursier (ex. "AAPL")
    use_cache : si True, retourne le résultat mis en cache
                pour éviter les appels API répétés
    """
    ticker = ticker.upper().strip()

    # 1a. Cache in-memory (15 min)
    if use_cache:
        cached = get_cached(ticker)
        if cached:
            return cached

    # 1b. Snapshot Supabase (< 12h) — évite le pipeline si données fraîches
    if use_cache:
        try:
            from snapshot import get_snapshot
            snap = get_snapshot(ticker)
            if snap:
                set_cached(ticker, snap, ttl_minutes=15)
                return snap
        except Exception as e:
            print(f"[Pipeline] get_snapshot erreur : {e}", flush=True)

    # ── Étapes 1-3 : collectes PARALLÉLISÉES ──────────────
    # Les sources sont réseau-dépendantes et indépendantes entre elles :
    # les exécuter en séquence additionne les latences (~18s), en
    # parallèle on ne paie que la plus lente de chaque vague (~10s).
    # ThreadPoolExecutor convient ici : le travail est I/O (attente
    # réseau), pas CPU — le GIL n'est pas un obstacle.
    #
    # Deux vagues, car news et événements dirigeants ont besoin du
    # nom de société / CEO que seul get_market_data() fournit :
    #   Vague A : marché ‖ insiders ‖ calibration (ne dépendent que du ticker)
    #   Vague B : news entreprise ‖ news secteur ‖ événements CEO
    from concurrent.futures import ThreadPoolExecutor

    def _sans_crash(label, fn, *args, defaut=None):
        """Isole chaque source : une panne ne coûte que SA donnée."""
        try:
            return fn(*args)
        except Exception as e:
            print(f"[Pipeline] {label} indisponible : {e}", flush=True)
            return defaut if defaut is not None else pd.DataFrame()

    def _calibration_safe(t):
        from analysis.calibration import poids_calibres
        return poids_calibres(t)

    with ThreadPoolExecutor(max_workers=4) as ex:
        # ── Vague A ──
        f_market = ex.submit(get_market_data, ticker)
        f_tx     = ex.submit(_sans_crash, "Transactions insiders",
                             get_insider_transactions, ticker)
        f_calib  = ex.submit(_sans_crash, "Calibration",
                             _calibration_safe, ticker, defaut=False)

        # market est CRITIQUE : son exception doit remonter (comportement
        # historique — pas d'analyse sans données marché)
        market = f_market.result()

        # ── Vague B (dépend de market) ──
        f_news   = ex.submit(_sans_crash, "News entreprise",
                             get_all_news, market["company_name"], ticker)
        f_sector = ex.submit(_sans_crash, "News sectorielles",
                             get_sector_news, market.get("sector", ""),
                             market.get("industry", ""))
        f_events = ex.submit(_sans_crash, "Événements dirigeants",
                             get_executive_events, market["ceo_name"], ticker)

        df_company  = f_news.result()
        df_sector   = f_sector.result()
        df_tx       = f_tx.result()
        df_events   = f_events.result()
        calibration = f_calib.result() or None   # False (échec) → None

    if not df_company.empty:
        df_company["type"] = "ticker"
    # Exclure les articles sectoriels déjà présents côté entreprise
    if not df_sector.empty and not df_company.empty:
        company_titles = set(df_company["titre"].str.lower())
        df_sector = df_sector[
            ~df_sector["titre"].str.lower().isin(company_titles)
        ]

    df_news   = pd.concat([df_company, df_sector], ignore_index=True)
    sentiment = analyze_sentiment(df_news)
    ins_score = get_insider_score(df_tx)

    # ── Étape 4 : calcul des 3 scores ─────────────────────
    # Calibration adaptative (calculée en vague A) : poids techniques
    # modulés par la fiabilité mesurée de chaque signal sur CE ticker.

    tech = score_technique(
        market,
        weights=calibration["weights"] if calibration else None,
    )
    fund  = score_fondamental(market)
    media_block  = compute_media_score(sentiment, ins_score, df_events)
    media        = media_block["score"]
    exec_risk    = compute_executive_risk_score(df_events, ins_score)

    # ── Étape 5 : score global et recommandation ──────────
    g_score_brut = score_global(tech["score"], fund["score"], media)

    # Ajustement par le régime de marché (QQQ) : un ACHETER quand le
    # NASDAQ plonge n'a pas la même valeur qu'en marché calme.
    # try/except large : l'analyse d'un ticker ne doit JAMAIS échouer
    # parce que QQQ est indisponible — sans contexte, score inchangé.
    g_score      = g_score_brut
    regime_ctx   = None
    regime_effet = None
    try:
        from analysis.market_regime import (
            get_market_context, get_qqq_history, apply_regime,
            compute_beta, compute_correlation,
        )
        regime_ctx = get_market_context()
        if regime_ctx:
            # Corrélation ticker/QQQ sur l'historique disponible (~45 séances) :
            # c'est le couplage RÉCENT au marché — plus pertinent pour un
            # ajustement du jour que la moyenne 2 ans du backtest, mais plus
            # bruité (erreur-type ~0.15). Acceptable car il ne fait que
            # MODULER un ajustement déjà borné (±6 pts).
            # None (historique trop court) → plein effet, prudence par défaut.
            corr = beta = None
            qqq  = get_qqq_history()
            if qqq is not None and "history" in market:
                corr = compute_correlation(market["history"]["Close"], qqq["Close"])
                beta = compute_beta(market["history"]["Close"], qqq["Close"])
            regime_effet = apply_regime(g_score_brut, regime_ctx, corr, beta)
            g_score      = regime_effet["score_ajuste"]
    except Exception as e:
        print(f"[Pipeline] régime marché ignoré : {e}", flush=True)

    reco_brute = recommandation(g_score)

    # ── Hystérésis : lisse les allers-retours de la recommandation ────────
    # Semaine du 13-19.07 sur TMC : le score a franchi les seuils
    # ACHETER/VENDRE six fois en une semaine — chaque franchissement
    # change la reco affichée et peut déclencher une escalade de conseil.
    # La reco STABLE n'adopte le changement que sur confirmation (2 calculs
    # frais consécutifs) ou un franchissement net (marge de 5 pts) — la
    # reco brute reste toujours visible, jamais masquée.
    reco = reco_brute
    hysteresis_info = None
    try:
        from analysis.hysteresis import appliquer_hysteresis
        from watchlist.watchlist import get_last_score, save_last_score
        etat_prec = get_last_score(ticker)
        reco, nouvel_etat = appliquer_hysteresis(g_score, etat_prec)
        save_last_score(ticker, g_score, reco, extra=nouvel_etat)
        hysteresis_info = {
            "reco_brute":   reco_brute,
            "reco_stable":  reco,
            "en_attente":   nouvel_etat.get("hyst_candidat"),
            "confirmations": nouvel_etat.get("hyst_streak", 0),
        }
    except Exception as e:
        print(f"[Pipeline] hystérésis ignorée : {e}", flush=True)

    # DataFrame récapitulatif des 3 composantes (Pandas)
    df_scores = pd.DataFrame([
        {"composante": "Technique",   "score": tech["score"], "poids": WEIGHT_TECH},
        {"composante": "Fondamental", "score": fund["score"], "poids": WEIGHT_FUND},
        {"composante": "Médiatique",  "score": media,         "poids": WEIGHT_MEDIA},
    ]).assign(
        contribution=lambda df: (df["score"] * df["poids"]).round(1)
    )

    # ── Construction du dict résultat ─────────────────────
    # IMPORTANT : result doit être créé AVANT l'appel au LLM
    # car generate_explanation() en a besoin pour construire le prompt
    result = {
        # Identification
        "ticker":         ticker,
        "company_name":   market["company_name"],
        "ceo_name":       market["ceo_name"],
        "sector":         market["sector"],
        # Recommandation finale
        "recommandation": reco,             # STABLE (lissée par hystérésis)
        "reco_brute":     reco_brute,       # brute, sans lissage — transparence
        "hysteresis":     hysteresis_info,  # {reco_brute, reco_stable, en_attente, confirmations}
        "score_global":   g_score,          # score APRÈS ajustement régime
        "score_brut":     g_score_brut,     # score avant contexte marché
        "market_regime":  regime_ctx,       # dict régime QQQ (ou None)
        "regime_effet":   regime_effet,     # {score_brut, score_ajuste, delta}
        # Détail des poids calibrés par ticker (liste sérialisable, ou None).
        # On ne stocke PAS la Series weights (inutile en aval, non-JSON).
        "calibration":    calibration["detail"] if calibration else None,
        "calibration_periode": calibration["periode"] if calibration else None,
        # Scores détaillés
        "score_tech":     tech["score"],
        "score_fund":     fund["score"],
        "score_media":    media,
        "df_scores":      df_scores,
        # Signaux détaillés
        "signals_tech":   tech["signals"],
        "signals_fund":   fund["signals"],
        # Données brutes
        "market":         market,
        "df_news":        sentiment["df_annote"],
        "sentiment":      sentiment,
        "df_insider":       df_tx,
        "df_events":        df_events,
        "insider_score":    ins_score,
        "media_detail":     media_block["detail"],
        "executive_risk":   exec_risk,
    }

    # ── Étape 6 : génération de l'explication LLM ────────
    # Appelé APRÈS la création de result (il en a besoin)
    # generate_explanation() gère Groq → Ollama → fallback
    # Elle ne lève jamais d'exception (triple filet de sécurité)
    if LLM_ENABLED:
        result["explication"] = generate_explanation(result)
    else:
        # LLM_ENABLED = False dans config.py → fallback Python direct
        result["explication"] = {
            "texte":  _fallback_text(result),
            "source": "fallback",
            "tokens": 0,
        }

    # Cache in-memory complet — history tronqué à 45 lignes, impact RAM négligeable
    set_cached(ticker, result, ttl_minutes=15)

    # Snapshot Supabase (silencieux si Supabase indisponible)
    try:
        from snapshot import save_snapshot
        save_snapshot(ticker, result)
    except Exception as e:
        print(f"[Pipeline] save_snapshot erreur : {e}", flush=True)

    return result

