# analysis/scoring_v2.py
# Version finale du scoring avec gestion des valeurs manquantes.
# Utilise pd.Series.fillna() et np.clip() pour la robustesse.

import numpy  as np
import pandas as pd
from config import WEIGHT_TECH, WEIGHT_FUND, WEIGHT_MEDIA, SCORE_BUY, SCORE_SELL


def normalize(val, vmin: float, vmax: float) -> float:
    """
    Normalise une valeur brute vers [0, 100].
    Utilisé pour les métriques continues (P/E, croissance…).
    """
    if val is None or pd.isna(val):
        return 50.0   # valeur neutre par défaut si donnée absente
    return float(np.clip((1 - (val - vmin) / max(vmax - vmin, 1)) * 100, 0, 100))


def score_fondamental_v2(data: dict) -> dict:
    """
    Score fondamental amélioré avec gestion des NaN.
    Chaque métrique est normalisée séparément
    puis agrégée via une moyenne Pandas pondérée.
    """
    # Stocke les métriques brutes dans une Series
    # .fillna(valeur_neutre) gère les données manquantes
    metrics = pd.Series({
        "pe_ratio":       data.get("pe_ratio"),
        "revenue_growth": data.get("revenue_growth"),
        "debt_equity":    data.get("debt_equity"),
        "eps":            data.get("eps"),
    })

    # Normalisation de chaque métrique vers [0, 100]
    # Les bornes sont définies d'après les valeurs typiques du marché
    scores_ind = pd.Series({
        "pe":     normalize(metrics["pe_ratio"],       5,   50),
        "growth": normalize(-metrics["revenue_growth"],-0.3, 0.5),  # inversé
        "debt":   normalize(metrics["debt_equity"],    0,   200),
        "eps":    70.0 if (metrics["eps"] or 0) > 0 else 30.0,
    })

    # Poids de chaque composante (somme = 1)
    poids = pd.Series({"pe": 0.35, "growth": 0.30, "debt": 0.20, "eps": 0.15})

    # Moyenne pondérée Pandas : produit élément par élément
    score = float((scores_ind * poids).sum())

    # DataFrame de décomposition pour l'explainer
    df_detail = pd.DataFrame({
        "métrique": scores_ind.index,
        "valeur":   metrics.reindex(["pe_ratio","revenue_growth","debt_equity","eps"]).values,
        "score":    scores_ind.values.round(1),
        "poids":    poids.values,
    })

    signals_out = [
        {"nom": row["métrique"], "points": round((row["score"] - 50) * row["poids"], 1),
         "sens": "haussier" if row["score"] > 50 else "baissier"}
        for _, row in df_detail.iterrows()
    ]

    return {"score": round(score, 1), "signals": signals_out, "detail": df_detail}


def score_global_v2(tech, fund, media) -> float:
    """Agrégation finale pondérée, robuste aux NaN."""
    scores = pd.Series({"tech": tech, "fund": fund, "media": media}).fillna(50)
    poids  = pd.Series({"tech": WEIGHT_TECH, "fund": WEIGHT_FUND, "media": WEIGHT_MEDIA})
    return round(float((scores * poids).sum()), 1)
