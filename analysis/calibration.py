# analysis/calibration.py — calibration adaptative des poids par ticker
#
# Dernière brique de la boucle conseille → mesure → corrige : l'attribution
# du backtest a montré que certains critères sont mal calibrés PAR TITRE
# (rsi_surachat pèse -20 partout alors qu'il n'est fiable qu'à 27% sur TMC).
# Ici, chaque poids manuel est modulé par la fiabilité MESURÉE du signal
# sur 2 ans — jamais remplacé aveuglément : le poids manuel reste la base,
# les données ne font que l'atténuer ou le renforcer.
#
# Trois garde-fous (c'est ici que ce genre de système déraille sinon) :
#   1. Shrinkage bayésien : la fiabilité observée est tirée vers 50% en
#      proportion inverse du nombre d'épisodes — 100% sur 5 épisodes ne
#      vaut pas 100% sur 50 (on ajoute K_PRIOR pseudo-épisodes neutres).
#   2. Bornes [0 ; 1.5] : un signal peut être éteint ou modérément
#      renforcé, JAMAIS inversé automatiquement — inverser un signal sur
#      données passées est le meilleur moyen d'overfitter un régime révolu
#      (leçon du classifieur : le régime change).
#   3. Minimum 8 épisodes : en dessous, poids inchangé — pas de décision
#      sur du bruit.
# Et une exigence : chaque ajustement est journalisé et affiché dans l'UI.

import numpy as np
import pandas as pd

from analysis.scoring import TECH_WEIGHTS, TECH_LABELS

K_PRIOR      = 10    # pseudo-épisodes neutres ajoutés (force du shrinkage)
PENTE        = 4     # sensibilité : multiplicateur = 1 + PENTE × (fiab' − 0.5)
M_MIN, M_MAX = 0.0, 1.5   # bornes du multiplicateur (éteindre oui, inverser non)
MIN_EPISODES = 8     # en dessous : aucune modification du poids


def facteur_fiabilite(hit_pct: float, n_episodes: int) -> float:
    """
    Convertit la fiabilité mesurée d'un signal en multiplicateur de poids.

    Étape 1 — shrinkage : fiab' = (n×fiab + K×50%) / (n + K).
      Ex. TMC rsi_surachat : 27.3% sur 11 épisodes
      → (11×0.273 + 10×0.5) / 21 = 38.1% (et non 27.3 brut).
    Étape 2 — pente autour du point neutre : à 50% de fiabilité le poids
      manuel est conservé tel quel (multiplicateur 1) — « présumé correct
      tant que les données ne prouvent pas le contraire ».
      multiplicateur = 1 + 4 × (0.381 − 0.5) = 0.52 → -20 devient -10.5.
    Étape 3 — bornes [0 ; 1.5].
    """
    if n_episodes < MIN_EPISODES:
        return 1.0
    fiab   = hit_pct / 100.0
    fiab_s = (n_episodes * fiab + K_PRIOR * 0.5) / (n_episodes + K_PRIOR)
    return round(float(np.clip(1 + PENTE * (fiab_s - 0.5), M_MIN, M_MAX)), 2)


def calibrer(attribution: list) -> tuple:
    """
    Transforme l'attribution du backtest en poids calibrés.
    Fonction PURE (liste de dicts → (pd.Series, liste)) : testable hors réseau.

    Retour :
      weights : pd.Series alignée sur TECH_WEIGHTS — les signaux absents
                de l'attribution (jamais actifs sur ce titre) gardent leur
                poids manuel
      detail  : liste des ajustements NON triviaux, pour l'affichage —
                chaque entrée dit quoi, de combien et pourquoi
    """
    weights = TECH_WEIGHTS.astype(float).copy()
    detail  = []

    for a in attribution or []:
        code = a.get("code")
        if code not in weights.index:
            continue
        m = facteur_fiabilite(a["hit_pct"], a["n_episodes"])
        if m == 1.0:
            continue
        base    = float(TECH_WEIGHTS[code])
        ajuste  = round(base * m, 1)
        weights[code] = ajuste
        detail.append({
            "code":        code,
            "label":       TECH_LABELS.get(code, code),
            "poids_base":  base,
            "poids_ajuste": ajuste,
            "facteur":     m,
            "hit_pct":     a["hit_pct"],
            "n_episodes":  a["n_episodes"],
        })

    # Les plus gros ajustements d'abord — ce sont eux qui expliquent
    # la différence entre score brut et score calibré
    detail.sort(key=lambda d: abs(d["poids_ajuste"] - d["poids_base"]),
                reverse=True)
    return weights, detail


def poids_calibres(ticker: str) -> dict | None:
    """
    Point d'entrée pipeline : poids calibrés pour un ticker.
    S'appuie sur le backtest (cache 1 h) — l'attribution y est déjà
    calculée. Retourne None si le backtest échoue : l'appelant DOIT
    fonctionner avec les poids manuels (aucune calibration ≠ panne).

    Note méthodo : le backtest, lui, rejoue toujours les poids MANUELS —
    mesurer l'attribution avec des poids déjà calibrés dessus serait
    circulaire (le thermomètre ne doit pas dépendre du chauffage).
    """
    try:
        from analysis.backtest import run_backtest
        res = run_backtest(ticker)
        weights, detail = calibrer(res.get("attribution", []))
        return {
            "weights":   weights,
            "detail":    detail,
            "n_ajustes": len(detail),
            "periode":   f'{res["date_debut"]} → {res["date_fin"]}',
        }
    except Exception as e:
        print(f"[Calibration] indisponible pour {ticker} : {e}", flush=True)
        return None
