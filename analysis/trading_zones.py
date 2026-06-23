# analysis/trading_zones.py
# Calcule les zones d'entrée, objectif et stop-loss à partir des indicateurs existants.
# Module indépendant — ne modifie aucun code existant.

import numpy as np
import pandas as pd

from config import SCORE_BUY, SCORE_SELL


def _safe(val, default=0.0):
    if val is None:
        return default
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _compute_atr(hist: pd.DataFrame, period: int = 14) -> float:
    """Average True Range sur `period` séances."""
    high  = hist["High"]
    low   = hist["Low"]
    close = hist["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return _safe(val, default=0.0)


def _first_resistance_above(price: float, *candidates) -> float | None:
    """Retourne la première valeur parmi candidates qui soit > price + marge."""
    above = sorted(v for v in candidates if v is not None and v > price * 1.005)
    return above[0] if above else None


def _first_support_below(price: float, *candidates) -> float | None:
    """Retourne la première valeur parmi candidates qui soit < price - marge."""
    below = sorted((v for v in candidates if v is not None and v < price * 0.995), reverse=True)
    return below[0] if below else None


def compute_trading_zones(
    hist: pd.DataFrame,
    market: dict,
    score: float,
    reco: str,
) -> dict:
    """
    Retourne les zones de trading basées sur les indicateurs disponibles dans le SDE.

    Les zones d'entrée et le stop-loss sont TOUJOURS du bon côté du prix courant :
    - ACHETER : entrée ≤ prix, stop < entrée, cible > prix
    - VENDRE  : entrée ≥ prix, stop > entrée, cible < prix

    Paramètres
    ----------
    hist   : DataFrame OHLCV enrichi retourné par get_market_data()
    market : dict retourné par get_market_data()
    score  : score global 0-100
    reco   : 'ACHETER' | 'NEUTRE' | 'VENDRE'

    Retour
    ------
    dict avec les clés :
      entry_low, entry_high   — plage d'entrée
      target_low, target_high — objectif de prix
      stop_loss               — niveau d'invalidation (None si NEUTRE)
      atr                     — ATR(14)
      rr_ratio                — risque/rendement (None si NEUTRE)
      support                 — plus bas sur 20 séances
      resistance              — plus haut sur 20 séances
      pct_target              — % entre prix et centre de l'objectif
      pct_stop                — % entre prix et stop-loss
      motif_entree            — label descriptif
      motif_cible             — label descriptif
    """
    price  = _safe(market.get("price"), 100.0)
    bb_up  = _safe(market.get("bb_upper"), None)
    bb_low = _safe(market.get("bb_lower"), None)

    atr = _compute_atr(hist)
    if atr == 0.0:
        atr = price * 0.015  # fallback : 1,5 % du prix courant

    # Support / résistance bruts sur les 20 dernières séances
    window     = min(20, len(hist))
    recent     = hist.iloc[-window:]
    support    = _safe(recent["Low"].min(),  price - atr)
    resistance = _safe(recent["High"].max(), price + atr)

    # Facteur de conviction → calibre l'amplitude de la zone cible
    # ACHETER : de 1,5× ATR (score=SCORE_BUY) à 2,5× (score=100)
    # VENDRE  : de 1,5× ATR (score=SCORE_SELL) à 2,5× (score=0)
    if reco == "ACHETER":
        factor = 1.5 + max(0.0, score - SCORE_BUY) / max(1.0, 100.0 - SCORE_BUY)
    elif reco == "VENDRE":
        factor = 1.5 + max(0.0, SCORE_SELL - score) / max(1.0, SCORE_SELL)
    else:
        factor = 1.0
    factor = min(factor, 2.5)

    # ── ACHETER ───────────────────────────────────────────────
    if reco == "ACHETER":
        # Entrée : pullback de 0,5–1,0 ATR — toujours SOUS le prix
        entry_low  = round(price - 1.0 * atr, 2)
        entry_high = round(price, 2)

        # Cible : première résistance STRICTEMENT au-dessus du prix
        # (bb_upper ou max 20j) sinon fallback ATR
        t_main = price + factor * atr
        t_tech = _first_resistance_above(price, bb_up, resistance)
        if t_tech is not None:
            target_low  = round(min(t_main, t_tech), 2)
            target_high = round(max(t_main, t_tech), 2)
            motif_cible = "Résistance BB / récente"
        else:
            # Ni bb_upper ni résistance au-dessus : objectif purement ATR
            target_low  = round(t_main * 0.97, 2)
            target_high = round(t_main, 2)
            motif_cible = "Objectif ATR (résistance non identifiée)"

        # Garde-fous : cible toujours au-dessus du prix d'entrée
        if target_low <= price:
            target_low = round(price + 0.3 * atr, 2)
        if target_high <= target_low:
            target_high = round(target_low + 0.5 * atr, 2)

        # Stop : 2× ATR sous le prix — toujours sous l'entrée
        stop_loss    = round(price - 2.0 * atr, 2)
        motif_entree = "Pullback 1× ATR → prix actuel"

    # ── VENDRE ────────────────────────────────────────────────
    elif reco == "VENDRE":
        # Entrée : rebond de 0,5 ATR — toujours AU-DESSUS ou AU prix
        entry_low  = round(price, 2)
        entry_high = round(price + 0.5 * atr, 2)

        # Cible : premier support STRICTEMENT sous le prix
        t_main = price - factor * atr
        t_tech = _first_support_below(price, bb_low, support)
        if t_tech is not None:
            target_low  = round(min(t_main, t_tech), 2)
            target_high = round(max(t_main, t_tech), 2)
            motif_cible = "Support BB / récent"
        else:
            target_low  = round(t_main, 2)
            target_high = round(t_main * 1.03, 2)
            motif_cible = "Objectif ATR (support non identifié)"

        # Garde-fous : cible toujours sous le prix d'entrée
        if target_high >= price:
            target_high = round(price - 0.3 * atr, 2)
        if target_low >= target_high:
            target_low = round(target_high - 0.5 * atr, 2)

        # Stop : 2× ATR au-dessus du prix — toujours au-dessus de l'entrée
        stop_loss    = round(price + 2.0 * atr, 2)
        motif_entree = "Prix actuel → rebond 0,5× ATR"

    # ── NEUTRE ────────────────────────────────────────────────
    else:
        entry_low  = round(price - 0.5 * atr, 2)
        entry_high = round(price + 0.5 * atr, 2)

        # Cible = résistance AU-DESSUS du prix uniquement
        # (pas de bb_low ici : ça créerait une cible sous l'entrée)
        t_up = _first_resistance_above(price, bb_up, resistance)
        target_low  = entry_high  # démarre où finit la zone neutre → jamais sous entrée
        target_high = round(t_up, 2) if t_up else round(price + 1.5 * atr, 2)
        # Assure un écart minimum pour que la plage soit lisible
        if target_high <= target_low:
            target_high = round(target_low + atr, 2)

        stop_loss   = None
        motif_entree = "Zone neutre · attendre un signal"
        motif_cible  = "Résistance (si cassure haussière)"

    # Support de référence affiché dans la colonne stop pour NEUTRE
    support_ref = round(
        bb_low if (bb_low is not None and bb_low < price)
        else (support if support < price else price - 1.5 * atr),
        2,
    ) if reco == "NEUTRE" else None

    # ── Ratio Risque / Rendement ──────────────────────────────
    if stop_loss is not None and abs(price - stop_loss) > 0:
        centre_target = (target_low + target_high) / 2.0
        gain = abs(centre_target - price)
        risk = abs(price - stop_loss)
        rr_ratio = round(gain / risk, 1) if risk > 0 else None
    else:
        rr_ratio = None

    # Variations % pour l'affichage
    centre_target = (target_low + target_high) / 2.0
    pct_target = round((centre_target - price) / price * 100, 1) if price else None
    pct_stop   = round((stop_loss - price)    / price * 100, 1) if (stop_loss and price) else None

    return {
        "entry_low":    entry_low,
        "entry_high":   entry_high,
        "target_low":   target_low,
        "target_high":  target_high,
        "stop_loss":    stop_loss,
        "support_ref":  support_ref,   # niveau de support affiché pour NEUTRE
        "atr":          round(atr, 2),
        "rr_ratio":     rr_ratio,
        "support":      round(support, 2),
        "resistance":   round(resistance, 2),
        "pct_target":   pct_target,
        "pct_stop":     pct_stop,
        "motif_entree": motif_entree,
        "motif_cible":  motif_cible,
    }
