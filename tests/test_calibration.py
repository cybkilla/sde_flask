# tests/test_calibration.py — tests de la calibration adaptative, hors réseau.
#
# facteur_fiabilite() et calibrer() sont des fonctions PURES : on leur
# fournit des attributions fabriquées et on vérifie les trois garde-fous
# (shrinkage, bornes, minimum d'épisodes) plus la transparence du détail.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from analysis.calibration import (
    facteur_fiabilite, calibrer,
    K_PRIOR, MIN_EPISODES, M_MIN, M_MAX,
)
from analysis.scoring import TECH_WEIGHTS, score_technique


# ── Garde-fou 1 : shrinkage — même fiabilité, confiance différente ──
# 30% de fiabilité sur 10 épisodes vs sur 100 : la version 100 épisodes
# doit être corrigée PLUS fort (les données pèsent plus que le prior).
m_10  = facteur_fiabilite(30.0, 10)
m_100 = facteur_fiabilite(30.0, 100)
assert m_100 < m_10 < 1.0, f"shrinkage inversé : m_10={m_10}, m_100={m_100}"
print(f"✓ shrinkage : fiab. 30% → ×{m_10} sur 10 ép., ×{m_100} sur 100 ép.")

# Fiabilité exactement 50% → poids inchangé (présumé correct)
assert facteur_fiabilite(50.0, 50) == 1.0
print("✓ fiabilité 50% → multiplicateur 1 (poids manuel conservé)")

# ── Garde-fou 2 : bornes — éteindre oui, inverser jamais ──
assert facteur_fiabilite(0.0, 200) == M_MIN     # signal toujours faux → 0
assert facteur_fiabilite(100.0, 200) == M_MAX   # excellent → plafonné à 1.5
print(f"✓ bornes : pire cas → ×{M_MIN} (éteint), meilleur cas → ×{M_MAX} (plafonné)")

# ── Garde-fou 3 : minimum d'épisodes ──
assert facteur_fiabilite(100.0, MIN_EPISODES - 1) == 1.0, \
    "moins de 8 épisodes ne doit RIEN changer, même à 100%"
print(f"✓ moins de {MIN_EPISODES} épisodes → poids inchangé (pas de décision sur du bruit)")

# ── calibrer() : Series alignée + détail transparent ──
attribution = [
    # Le cas TMC réel : rsi_surachat peu fiable, bien documenté
    {"code": "rsi_surachat", "hit_pct": 27.3, "n_episodes": 11},
    # Signal fiable → renforcé
    {"code": "trend_5j_fort", "hit_pct": 63.2, "n_episodes": 38},
    # Trop peu d'épisodes → ignoré
    {"code": "rsi_survente", "hit_pct": 100.0, "n_episodes": 5},
    # Code inconnu → ignoré sans crash
    {"code": "signal_fantome", "hit_pct": 10.0, "n_episodes": 50},
]
weights, detail = calibrer(attribution)

# Tous les signaux existent dans la Series, même les non-ajustés
assert set(weights.index) == set(TECH_WEIGHTS.index)
# rsi_surachat atténué mais PAS inversé (reste négatif)
assert -20 < weights["rsi_surachat"] < 0
# trend_5j_fort renforcé
assert weights["trend_5j_fort"] > TECH_WEIGHTS["trend_5j_fort"]
# rsi_survente intact (5 épisodes < 8)
assert weights["rsi_survente"] == TECH_WEIGHTS["rsi_survente"]
# Détail : seulement les ajustements réels, triés par ampleur décroissante
codes_detail = [d["code"] for d in detail]
assert "rsi_survente" not in codes_detail and "signal_fantome" not in codes_detail
ecarts = [abs(d["poids_ajuste"] - d["poids_base"]) for d in detail]
assert ecarts == sorted(ecarts, reverse=True)
print("✓ calibrer : atténue sans inverser, renforce, ignore le bruit, détail trié")

# Attribution vide / None → poids manuels intacts, détail vide
w_vide, d_vide = calibrer([])
assert (w_vide == TECH_WEIGHTS).all() and d_vide == []
w_none, d_none = calibrer(None)
assert (w_none == TECH_WEIGHTS).all() and d_none == []
print("✓ attribution vide ou None → poids manuels, pas de crash")

# ── score_technique(weights=...) : l'injection change bien le score ──
# Historique synthétique en forte hausse 5j → trend_5j_fort actif
np.random.seed(4)
n = 80
close = pd.Series(np.linspace(100, 130, n)) + np.random.normal(0, 0.3, n)
hist  = pd.DataFrame({
    "Close": close, "Open": close, "High": close * 1.01, "Low": close * 0.99,
    "Volume": np.full(n, 2_000_000.0),
})
from utils.indicators import add_indicators
hist = hist.pipe(add_indicators)
hist["Ret_5d"]    = (hist["Close"].pct_change(5) * 100).round(2)
hist["Vol_ratio"] = (hist["Volume"] / hist["Volume"].rolling(20).mean()).round(2)

score_std   = score_technique({"history": hist})["score"]
w_boost     = TECH_WEIGHTS.astype(float).copy()
w_boost[:]  = w_boost * 1.5          # tous les poids amplifiés
score_boost = score_technique({"history": hist}, weights=w_boost)["score"]
assert score_boost != score_std, "des poids différents doivent changer le score"
# Sans le paramètre → identique à l'appel historique (rétro-compatibilité)
assert score_technique({"history": hist}, weights=None)["score"] == score_std
print(f"✓ score_technique : poids injectés pris en compte ({score_std} → {score_boost}), rétro-compatible")

print("\n✓ Tous les tests test_calibration.py sont OK (hors réseau)")
