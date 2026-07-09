# analysis/scoring.py
# Moteur de score pondéré — agrège les 3 dimensions
# (technique, fondamental, médiatique) en un score 0–100.

import numpy as np
import pandas as pd
from analysis.signals import compute_tech_signals
from config import (
    WEIGHT_TECH, WEIGHT_FUND, WEIGHT_MEDIA,
    SCORE_BUY, SCORE_SELL,
)


# ── Poids et labels des signaux techniques ────────────────
# Hissés au niveau module (et non locaux à score_technique) pour servir
# de source unique de vérité : le backtest et la future calibration
# adaptative les importent d'ici — jamais de copie qui pourrait diverger.
TECH_WEIGHTS = pd.Series({
    "rsi_survente":    20,   # RSI < 30 → signal haussier fort
    "rsi_bas":          10,   # RSI 30-45 → légèrement haussier
    "rsi_haut":        -10,   # RSI 55-70 → légèrement baissier
    "rsi_surachat":    -20,   # RSI > 70 → signal baissier fort
    "ma_cross_up":      15,   # MA20 > MA50 → tendance haussière
    "ma_cross_down":   -15,   # MA20 < MA50 → tendance baissière
    "macd_bull":        10,   # MACD > Signal line → momentum +
    "macd_bear":       -10,   # MACD < Signal line → momentum -
    "vol_anormal":       8,   # Volume > 2x moyenne → signal fort
    "prix_bb_haut":     -8,   # Prix > bande Bollinger haute
    "prix_bb_bas":       8,   # Prix < bande Bollinger basse
    "trend_5j_fort":     8,   # Variation 5j > +5%
    "trend_5j_mod":      4,   # Variation 5j > +2%
    "trend_5j_neg":     -8,   # Variation 5j < -5%
    "trend_5j_neg_mod": -4,   # Variation 5j < -2%
})

TECH_LABELS = {
    "rsi_survente":    "RSI en zone de survente (< 30)",
    "rsi_bas":         "RSI dans zone basse (30-45)",
    "rsi_haut":        "RSI dans zone haute (55-70)",
    "rsi_surachat":    "RSI en zone de surachat (> 70)",
    "ma_cross_up":     "Croisement haussier MA20 > MA50",
    "ma_cross_down":   "Croisement baissier MA20 < MA50",
    "macd_bull":       "MACD au-dessus de sa ligne de signal",
    "macd_bear":       "MACD sous sa ligne de signal",
    "vol_anormal":     "Volume > 2x la moyenne 20j",
    "prix_bb_haut":    "Prix au-dessus de Bollinger haute",
    "prix_bb_bas":     "Prix en dessous de Bollinger basse",
    "trend_5j_fort":   "Tendance 5j forte (> +5%)",
    "trend_5j_mod":    "Tendance 5j modérée (> +2%)",
    "trend_5j_neg":    "Tendance 5j négative (< -5%)",
    "trend_5j_neg_mod":"Tendance 5j mod. négative (< -2%)",
}


# ── Score technique (Jours 4-5) ───────────────────────────
def score_technique(data: dict, weights: pd.Series = None) -> dict:
    """
    Calcule le score technique depuis le DataFrame Pandas enrichi.

    Paramètres
    ----------
    data    : dict retourné par get_market_data()
              data['history'] est le DataFrame OHLCV + indicateurs.
    weights : poids alternatifs (ex. calibrés par ticker via
              analysis/calibration.py). None → TECH_WEIGHTS manuels.
              Le backtest n'utilise JAMAIS ce paramètre : l'attribution
              doit être mesurée sur les poids de base (sinon circularité).

    Retour
    ------
    dict avec :
      'score'   : float 0-100
      'signals' : liste de dicts décrivant chaque signal détecté
      'detail'  : pd.Series avec la contribution de chaque signal
    """
    hist = data["history"]   # DataFrame Pandas
    last = hist.iloc[-1]    # dernière ligne → pd.Series

    # Tous les signaux binaires / scalaires sont calculés
    # dans signals.py et retournés sous forme de pd.Series
    signals_series = compute_tech_signals(hist)

    # --- Contribution de chaque signal au score --------
    # Les poids {nom: +/- points} vivent au niveau module (TECH_WEIGHTS)
    # Pandas permet de vectoriser la somme finale proprement.
    if weights is None:
        weights = TECH_WEIGHTS

    # Intersection : ne prend que les signaux activés
    # signals_series est un pd.Series booléen {nom: True/False}
    active = signals_series[signals_series]              # filtre True
    contribution = weights.reindex(active.index).fillna(0)

    # Score final : base 50 + somme des contributions activées
    score_raw = 50.0 + contribution.sum()
    score     = float(np.clip(score_raw, 0, 100))

    # Liste lisible des signaux pour l'affichage UI.
    # "code" = clé machine stable (ex. "rsi_surachat") — indispensable pour
    # stocker les signaux en base et les relier plus tard aux évaluations,
    # là où "nom" (label français) peut changer de formulation.
    signals_out = [
        {
            "code":   k,
            "nom":    TECH_LABELS.get(k, k),
            "points": weights.get(k, 0),
            "sens":   "haussier" if weights.get(k, 0) > 0 else "baissier",
        }
        for k in active.index
    ]

    return {
        "score":       round(score, 1),
        "signals":     signals_out,
        "contribution":contribution,  # pd.Series, utile pour debug
    }


# ── Score fondamental ──────────────────────────────────────
def score_fondamental(data: dict) -> dict:
    """
    Score fondamental basé sur les ratios yfinance.
    Utilise pd.Series pour vectoriser les comparaisons.
    """
    # On place les métriques dans une Series pour
    # pouvoir appliquer des opérations Pandas dessus
    metrics = pd.Series({
        "pe_ratio":       data.get("pe_ratio")       or 25,
        "revenue_growth": data.get("revenue_growth") or 0,
        "debt_equity":    data.get("debt_equity")    or 50,
        "eps":            data.get("eps"),
    })

    score = 50.0
    signals_out = []

    # P/E ratio ────────────────────────────────────
    pe = metrics["pe_ratio"]
    if   pe < 15: score += 20; signals_out.append({"nom":"P/E attractif (< 15)",        "points":20,"sens":"haussier"})
    elif pe < 25: score += 10; signals_out.append({"nom":"P/E raisonnable (15-25)",     "points":10,"sens":"haussier"})
    elif pe > 40: score -= 20; signals_out.append({"nom":"P/E très élevé (> 40)",       "points":-20,"sens":"baissier"})
    elif pe > 30: score -= 10; signals_out.append({"nom":"P/E élevé (30-40)",          "points":-10,"sens":"baissier"})

    # Croissance du chiffre d'affaires ────────────
    g = metrics["revenue_growth"]
    pts_g = round(float(np.clip(g * 100, -20, 20)), 1)
    score += pts_g
    signals_out.append({"nom":f"Croissance CA : {g*100:.1f}%","points":pts_g,
                        "sens":"haussier" if pts_g >= 0 else "baissier"})

    # Dette / capitaux propres ────────────────────
    d = metrics["debt_equity"]
    if   d < 30:  score += 10; signals_out.append({"nom":"Dette faible (< 30)",  "points":10, "sens":"haussier"})
    elif d > 150: score -= 15; signals_out.append({"nom":"Endettement élevé (> 150)","points":-15,"sens":"baissier"})

    # EPS positif / négatif (ignoré si donnée absente)
    eps = metrics["eps"]
    if pd.notna(eps):
        if eps > 0: score += 5;  signals_out.append({"nom":"EPS positif","points":5, "sens":"haussier"})
        else:       score -= 10; signals_out.append({"nom":"EPS négatif","points":-10,"sens":"baissier"})

    return {
        "score":  round(float(np.clip(score, 0, 100)), 1),
        "signals":signals_out,
    }


# ── Agrégation globale ─────────────────────────────────────
def score_global(tech: float, fund: float, media: float) -> float:
    """Moyenne pondérée des 3 scores → valeur 0-100."""
    return round(
        tech  * WEIGHT_TECH  +
        fund  * WEIGHT_FUND  +
        media * WEIGHT_MEDIA, 1
    )


def recommandation(score: float) -> str:
    """Convertit le score numérique en signal texte."""
    if   score > SCORE_BUY:  return "ACHETER"
    elif score < SCORE_SELL: return "VENDRE"
    else:                    return "NEUTRE"