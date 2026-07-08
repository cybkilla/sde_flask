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

    # ── Étape 1 : données marché (critique) ──────────────
    market = get_market_data(ticker)

    # ── Étape 2 : actualités + sentiment (non-critique) ──
    try:
        df_company = get_all_news(market["company_name"], ticker)
        if not df_company.empty:
            df_company["type"] = "ticker"
    except Exception as e:
        print(f"[Pipeline] News entreprise indisponibles : {e}")
        df_company = pd.DataFrame()

    try:
        df_sector = get_sector_news(market.get("sector", ""), market.get("industry", ""))
        if not df_sector.empty and not df_company.empty:
            company_titles = set(df_company["titre"].str.lower())
            df_sector = df_sector[
                ~df_sector["titre"].str.lower().isin(company_titles)
            ]
    except Exception as e:
        print(f"[Pipeline] News sectorielles indisponibles : {e}")
        df_sector = pd.DataFrame()

    df_news   = pd.concat([df_company, df_sector], ignore_index=True)
    sentiment = analyze_sentiment(df_news)

    # ── Étape 3 : insider + événements dirigeants (non-critique) ──
    try:
        df_tx = get_insider_transactions(ticker)
    except Exception as e:
        print(f"[Pipeline] Transactions insiders indisponibles : {e}")
        df_tx = pd.DataFrame()

    try:
        df_events = get_executive_events(market["ceo_name"], ticker)
    except Exception as e:
        print(f"[Pipeline] Événements dirigeants indisponibles : {e}")
        df_events = pd.DataFrame()

    ins_score = get_insider_score(df_tx)

    # ── Étape 4 : calcul des 3 scores ─────────────────────
    tech  = score_technique(market)
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
        from analysis.market_regime import get_market_context, apply_regime
        regime_ctx = get_market_context()
        if regime_ctx:
            regime_effet = apply_regime(g_score_brut, regime_ctx)
            g_score      = regime_effet["score_ajuste"]
    except Exception as e:
        print(f"[Pipeline] régime marché ignoré : {e}", flush=True)

    reco = recommandation(g_score)

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
        "recommandation": reco,
        "score_global":   g_score,          # score APRÈS ajustement régime
        "score_brut":     g_score_brut,     # score avant contexte marché
        "market_regime":  regime_ctx,       # dict régime QQQ (ou None)
        "regime_effet":   regime_effet,     # {score_brut, score_ajuste, delta}
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

