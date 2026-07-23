# analysis/market_regime.py — contexte macro : régime de marché via QQQ
#
# Problème résolu : SDE analysait chaque ticker en isolation. Un ACHETER
# quand le NASDAQ plonge de 3% n'a pas la même valeur qu'en marché calme —
# l'attribution du backtest l'a d'ailleurs montré : les signaux baissiers
# de SDE échouent massivement (27% sur TMC) parce qu'ils ignorent que le
# marché global était haussier.
#
# Pourquoi QQQ et pas ^VIX : le VIX (indice CBOE) n'est pas disponible sur
# Twelve Data — notre fallback obligatoire sur Render où yfinance est
# rate-limité. QQQ est un ETF coté normalement, disponible partout, et sa
# volatilité réalisée sur 20 jours joue le rôle de "proxy de peur".
#
# Philosophie SDE conservée : deux règles transparentes et bornées,
# affichées telles quelles dans l'UI — pas de boîte noire.

import time
import numpy as np
import pandas as pd

# Seuils des règles — volontairement simples et nommés pour être lisibles
SEUIL_VAR5J_BAISSIER = -3.0    # QQQ perd > 3% en 5j → marché baissier
SEUIL_VAR5J_CALME    = -1.0    # au-dessus, la tendance MA50 fait foi
SEUIL_VOL_ANNUALISEE = 30.0    # vol réalisée 20j annualisée > 30% → nerveux

AJUSTEMENT = {"haussier": +4, "neutre": 0, "baissier": -6}
FACTEUR_CONVICTION_VOLATIL = 0.7   # en marché nerveux : conviction réduite de 30%

# Pondération de l'ajustement par la sensibilité RÉELLE du titre au marché.
# Leçon du backtest (TMC vs AAPL) : le bêta seul est trompeur — TMC a un
# bêta de 1.45 mais une corrélation de 0.30 seulement. Le bêta mesure
# l'AMPLITUDE de réaction quand le titre suit le marché ; le R² (corrélation
# au carré) mesure la part de ses mouvements RÉELLEMENT expliquée par le
# marché. C'est donc le R² qui pondère : TMC (R² 0.09) ignore quasi
# totalement le régime, AAPL (R² 0.37) l'applique à ~40%.
BETA_MIN_JOURS = 30    # en dessous de 30 rendements communs : stats non fiables

# Cache module : le contexte macro est LE MÊME pour tous les tickers —
# inutile de re-télécharger QQQ à chaque analyse. TTL 1 h.
_CACHE: dict = {}
_CACHE_TTL_S = 3600


def _fetch_qqq(sessions: int = 130) -> pd.DataFrame:
    """
    ~130 séances (6 mois) de QQQ : assez pour une MA50 stable.
    Même stratégie de repli que partout : yfinance → Twelve Data.
    """
    hist = pd.DataFrame()
    try:
        import yfinance as yf
        from utils.net_timeout import with_timeout
        hist = with_timeout(lambda: yf.Ticker("QQQ").history(period="6mo"), 15)
    except Exception as e:
        print(f"[Regime] yfinance erreur (QQQ) : {e}", flush=True)

    if hist is None or hist.empty:
        from data.market import _get_candles_td
        print("[Regime] fallback Twelve Data pour QQQ", flush=True)
        hist = _get_candles_td("QQQ", sessions)

    if hist is None or hist.empty:
        raise ValueError("Impossible de récupérer l'historique QQQ")

    if getattr(hist.index, "tz", None) is not None:
        hist.index = hist.index.tz_localize(None)
    return hist


def compute_regime(qqq_hist: pd.DataFrame) -> dict:
    """
    Classe le marché en haussier / neutre / baissier + drapeau "volatil".
    Fonction PURE (DataFrame → dict) : testable sans réseau.

    Règles (transparentes, dans l'ordre) :
      baissier : QQQ sous sa MA50  OU  chute > 3% en 5 jours
      haussier : QQQ au-dessus de sa MA50  ET  pas de repli > 1% en 5 jours
      neutre   : tout le reste
      volatil  : vol réalisée 20j annualisée > 30% (indépendant de la tendance)
    """
    close = qqq_hist["Close"]
    if len(close) < 55:
        raise ValueError(f"Historique QQQ trop court ({len(close)} jours)")

    ma50   = close.rolling(50).mean().iloc[-1]
    dernier = float(close.iloc[-1])
    var_5j  = float(close.pct_change(5).iloc[-1] * 100)

    # Volatilité réalisée : écart-type des rendements quotidiens sur 20j,
    # annualisé par √252 (convention finance : 252 séances par an)
    vol_ann = float(close.pct_change().rolling(20).std().iloc[-1]
                    * np.sqrt(252) * 100)

    if dernier < ma50 or var_5j < SEUIL_VAR5J_BAISSIER:
        regime = "baissier"
    elif dernier > ma50 and var_5j > SEUIL_VAR5J_CALME:
        regime = "haussier"
    else:
        regime = "neutre"

    return {
        "regime":      regime,
        "volatil":     vol_ann > SEUIL_VOL_ANNUALISEE,
        "var_5j":      round(var_5j, 2),
        "vs_ma50_pct": round((dernier / float(ma50) - 1) * 100, 2),
        "vol_20j_ann": round(vol_ann, 1),
        "date":        str(qqq_hist.index[-1].date()),
    }


def _index_naif(s: pd.Series) -> pd.Series:
    """
    Normalise l'index en dates simples sans fuseau horaire.
    Indispensable avant .align() : yfinance renvoie des index tz-aware
    (America/New_York) alors que Twelve Data et nos caches sont tz-naïfs —
    Pandas refuse de joindre les deux ("Cannot join tz-naive with tz-aware").
    """
    s = s.copy()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()
    return s


def _rendements_communs(ticker_close: pd.Series, qqq_close: pd.Series):
    """
    Rendements quotidiens des deux titres sur leurs jours de cotation
    COMMUNS. .align(join='inner') ne garde que les dates présentes des
    deux côtés — indispensable, jours fériés différents possibles.
    Retourne (None, None) si moins de 30 jours communs (stats non fiables).
    """
    t, q = _index_naif(ticker_close).align(_index_naif(qqq_close), join="inner")
    r_t  = t.pct_change().dropna()
    r_q  = q.pct_change().dropna()
    r_t, r_q = r_t.align(r_q, join="inner")
    if len(r_t) < BETA_MIN_JOURS:
        return None, None
    return r_t, r_q


def compute_beta(ticker_close: pd.Series, qqq_close: pd.Series):
    """
    Bêta du ticker vs QQQ : de combien le titre bouge quand le marché
    bouge de 1%. Formule classique : cov(r_ticker, r_qqq) / var(r_qqq).
    Gardé pour l'AFFICHAGE (amplitude) — la pondération utilise le R².
    """
    r_t, r_q = _rendements_communs(ticker_close, qqq_close)
    if r_t is None:
        return None
    var_q = float(r_q.var())
    if var_q == 0 or np.isnan(var_q):
        return None
    return round(float(r_t.cov(r_q) / var_q), 2)


def compute_correlation(ticker_close: pd.Series, qqq_close: pd.Series):
    """Corrélation des rendements quotidiens ticker/QQQ. None si trop court."""
    r_t, r_q = _rendements_communs(ticker_close, qqq_close)
    if r_t is None:
        return None
    corr = float(r_t.corr(r_q))
    return None if np.isnan(corr) else round(corr, 2)


def sensibilite_marche(corr) -> float:
    """
    Sensibilité = R² = corrélation², dans [0 ; 1].
    C'est la part de variance du titre expliquée par le marché — donc la
    fraction de l'ajustement de régime qui a un sens pour ce titre.
    Corrélation négative → 0 (on n'inverse pas l'effet, on l'annule).
    None (inconnu) → 1.0 : plein effet, prudence par défaut.
    """
    if corr is None:
        return 1.0
    return round(max(float(corr), 0.0) ** 2, 2)


def apply_regime(score: float, ctx: dict, corr=None, beta=None) -> dict:
    """
    Module le score global selon le contexte, PONDÉRÉ par la part des
    mouvements du titre expliquée par le marché (R²). Fonction PURE.

    Trois effets successifs :
      1. Tendance : +4 (haussier) / 0 / -6 (baissier) — asymétrique car
         rater une hausse coûte moins cher que d'acheter dans une chute.
      2. Pondération R² : une small cap décorrélée (R² ~0.1) ignore
         quasiment le régime ; un titre qui suit le NASDAQ (R² ~0.5)
         l'applique à moitié.
      3. Volatilité : le score est tiré vers 50 (la neutralité), là aussi
         proportionnellement au R² — la nervosité du NASDAQ ne dit rien
         sur un titre qui ne le suit pas.

    Retourne l'avant/après pour que l'UI puisse afficher "62 → 56".
    """
    sens   = sensibilite_marche(corr)
    ajuste = score + AJUSTEMENT.get(ctx.get("regime", "neutre"), 0) * sens
    if ctx.get("volatil"):
        # Facteur effectif : R² 1 → 0.7 ; R² 0 → 1.0 (aucune réduction)
        facteur = 1 - (1 - FACTEUR_CONVICTION_VOLATIL) * sens
        ajuste  = 50 + (ajuste - 50) * facteur
    ajuste = round(float(np.clip(ajuste, 0, 100)), 1)

    return {
        "score_brut":   round(float(score), 1),
        "score_ajuste": ajuste,
        "delta":        round(ajuste - score, 1),
        "correlation":  corr,
        "beta":         beta,
        "sensibilite":  sens,
    }


def get_qqq_history() -> pd.DataFrame:
    """
    Historique QQQ mis en cache 1 h (partagé avec get_market_context —
    un seul téléchargement pour le régime ET les calculs de bêta).
    Retourne None en cas d'échec.
    """
    if "qqq" in _CACHE:
        ts, hist = _CACHE["qqq"]
        if time.time() - ts < _CACHE_TTL_S:
            return hist
    try:
        hist = _fetch_qqq()
        _CACHE["qqq"] = (time.time(), hist)
        return hist
    except Exception as e:
        print(f"[Regime] QQQ indisponible : {e}", flush=True)
        return None


def get_market_context() -> dict:
    """
    Point d'entrée : contexte macro du jour, mis en cache 1 h.
    Retourne None en cas d'échec — l'appelant DOIT fonctionner sans
    contexte (l'analyse d'un ticker ne peut pas casser à cause de QQQ).
    """
    if "ctx" in _CACHE:
        ts, ctx = _CACHE["ctx"]
        if time.time() - ts < _CACHE_TTL_S:
            return ctx
    try:
        hist = get_qqq_history()
        if hist is None:
            return None
        ctx = compute_regime(hist)
        _CACHE["ctx"] = (time.time(), ctx)
        return ctx
    except Exception as e:
        print(f"[Regime] contexte indisponible : {e}", flush=True)
        return None
