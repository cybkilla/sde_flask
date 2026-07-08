# tests/test_market_regime.py — tests des règles de régime marché, hors réseau.
#
# compute_regime() et apply_regime() sont des fonctions PURES : on leur
# fabrique des historiques QQQ synthétiques qui déclenchent chaque règle,
# et on vérifie la classification — aucun appel réseau.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from analysis.market_regime import (
    compute_regime, apply_regime,
    SEUIL_VOL_ANNUALISEE, AJUSTEMENT, FACTEUR_CONVICTION_VOLATIL,
)


def make_qqq(pente_quotidienne: float, bruit: float = 0.001,
             n: int = 120, seed: int = 7) -> pd.DataFrame:
    """
    QQQ synthétique : dérive quotidienne contrôlée + bruit faible.
    pente_quotidienne = +0.3%/jour → marché clairement haussier,
    -0.3%/jour → clairement baissier. Le bruit faible garde la vol basse.
    """
    np.random.seed(seed)
    close = 400 * np.cumprod(1 + np.random.normal(pente_quotidienne, bruit, n))
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame({"Close": close}, index=dates)


# ── Classification de la tendance ──
ctx_bull = compute_regime(make_qqq(+0.003))
assert ctx_bull["regime"] == "haussier", f"attendu haussier, obtenu {ctx_bull['regime']}"
assert not ctx_bull["volatil"]           # bruit 0.1%/j → vol annualisée ~1.6%

ctx_bear = compute_regime(make_qqq(-0.003))
assert ctx_bear["regime"] == "baissier"
print("✓ compute_regime : haussier et baissier correctement classés")

# Chute brutale récente (> 3% en 5j) → baissier MÊME si toujours au-dessus MA50.
# On monte longtemps puis on casse : -1%/jour sur les 4 derniers jours.
df_crash = make_qqq(+0.003)
df_crash.iloc[-4:, 0] = df_crash["Close"].iloc[-5] * np.cumprod([0.99] * 4)
ctx_crash = compute_regime(df_crash)
assert ctx_crash["regime"] == "baissier", "une chute > 3%/5j doit forcer baissier"
print("✓ compute_regime : chute brutale récente → baissier malgré la MA50")

# Volatilité élevée : bruit 3%/jour → vol annualisée ~48% > seuil 30%
ctx_vol = compute_regime(make_qqq(+0.003, bruit=0.03))
assert ctx_vol["volatil"], f"vol {ctx_vol['vol_20j_ann']}% devrait dépasser {SEUIL_VOL_ANNUALISEE}%"
print("✓ compute_regime : marché nerveux détecté (drapeau volatil)")


# ── Ajustement du score ──
# Marché baissier calme : -6 points, ni plus ni moins
eff = apply_regime(62, {"regime": "baissier", "volatil": False})
assert eff["score_ajuste"] == 62 + AJUSTEMENT["baissier"]
assert eff["delta"] == AJUSTEMENT["baissier"]

# Marché haussier calme : +4
assert apply_regime(50, {"regime": "haussier", "volatil": False})["score_ajuste"] == 54

# Volatil : la conviction est tirée vers 50 — le sens est PRÉSERVÉ
# (un score haussier reste haussier, juste moins confiant)
eff_v = apply_regime(70, {"regime": "neutre", "volatil": True})
attendu = 50 + (70 - 50) * FACTEUR_CONVICTION_VOLATIL
assert eff_v["score_ajuste"] == round(attendu, 1)
assert eff_v["score_ajuste"] > 50          # toujours côté achat

# Symétrie : un score baissier (30) remonte VERS 50, sans changer de camp
eff_v2 = apply_regime(30, {"regime": "neutre", "volatil": True})
assert 30 < eff_v2["score_ajuste"] < 50
print("✓ apply_regime : ajustements exacts, conviction réduite sans inverser le sens")

# Contexte absent/inconnu → score inchangé (robustesse)
assert apply_regime(62, {})["score_ajuste"] == 62.0
print("✓ apply_regime : contexte vide → score inchangé")

print("\n✓ Tous les tests test_market_regime.py sont OK (hors réseau)")
