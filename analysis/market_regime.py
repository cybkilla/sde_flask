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
        hist = yf.Ticker("QQQ").history(period="6mo")
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


def apply_regime(score: float, ctx: dict) -> dict:
    """
    Module le score global selon le contexte. Fonction PURE.

    Deux effets successifs :
      1. Tendance : +4 (haussier) / 0 / -6 (baissier) — asymétrique car
         rater une hausse coûte moins cher que d'acheter dans une chute.
      2. Volatilité : le score est tiré vers 50 (la neutralité) de 30%.
         L'incertitude ne rend ni haussier ni baissier — elle réduit la
         CONVICTION, quel que soit son sens.

    Retourne l'avant/après pour que l'UI puisse afficher "62 → 56".
    """
    ajuste = score + AJUSTEMENT.get(ctx.get("regime", "neutre"), 0)
    if ctx.get("volatil"):
        ajuste = 50 + (ajuste - 50) * FACTEUR_CONVICTION_VOLATIL
    ajuste = round(float(np.clip(ajuste, 0, 100)), 1)

    return {
        "score_brut":   round(float(score), 1),
        "score_ajuste": ajuste,
        "delta":        round(ajuste - score, 1),
    }


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
        ctx = compute_regime(_fetch_qqq())
        _CACHE["ctx"] = (time.time(), ctx)
        return ctx
    except Exception as e:
        print(f"[Regime] contexte indisponible : {e}", flush=True)
        return None
