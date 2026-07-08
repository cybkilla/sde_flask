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
    compute_regime, apply_regime, compute_beta, compute_correlation,
    sensibilite_marche,
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


# ── Bêta, corrélation et sensibilité (R²) ──
# Ticker = 2× les rendements du QQQ (avec un peu de bruit) → bêta ≈ 2,
# corrélation ≈ 1. Le clone amplifié DOIT être vu comme très lié au marché.
np.random.seed(11)
r_qqq  = np.random.normal(0.001, 0.012, 100)
dates  = pd.bdate_range("2025-01-02", periods=100)
qqq_px = pd.Series(400 * np.cumprod(1 + r_qqq), index=dates)
amp_px = pd.Series(50  * np.cumprod(1 + 2 * r_qqq + np.random.normal(0, 0.001, 100)), index=dates)

beta_amp = compute_beta(amp_px, qqq_px)
corr_amp = compute_correlation(amp_px, qqq_px)
assert 1.8 < beta_amp < 2.2,  f"bêta d'un clone 2x devrait être ~2, obtenu {beta_amp}"
assert corr_amp > 0.95,        f"corrélation d'un clone devrait être ~1, obtenue {corr_amp}"
assert sensibilite_marche(corr_amp) > 0.9

# Ticker au bruit indépendant → corrélation ~0 → sensibilité ~0
indep_px = pd.Series(20 * np.cumprod(1 + np.random.normal(0.002, 0.04, 100)), index=dates)
corr_ind = compute_correlation(indep_px, qqq_px)
assert abs(corr_ind) < 0.25, f"titre indépendant : corrélation ~0 attendue, obtenue {corr_ind}"
assert sensibilite_marche(corr_ind) < 0.07   # R² = corr² → encore plus petit
print("✓ compute_beta/correlation : clone 2x et titre indépendant bien mesurés")

# Corrélation négative → sensibilité 0 (on annule, on n'inverse pas)
assert sensibilite_marche(-0.6) == 0.0
# Inconnu → plein effet (prudence)
assert sensibilite_marche(None) == 1.0
# Historique commun trop court (< 30 j) → None
assert compute_beta(amp_px.head(10), qqq_px.head(10)) is None
print("✓ sensibilite_marche : négatif → 0, inconnu → 1, historique court → None")

# ── apply_regime pondéré par le R² ──
# R² faible (TMC-like, corr 0.3 → R² 0.09) : l'ajustement baissier -6
# devient -0.54 — quasi rien
eff_tmc = apply_regime(62, {"regime": "baissier", "volatil": False}, corr=0.3)
assert abs(eff_tmc["delta"] - (-6 * 0.09)) < 0.06
assert eff_tmc["sensibilite"] == 0.09

# Corrélation parfaite → plein effet, identique à l'ancien comportement
eff_full = apply_regime(62, {"regime": "baissier", "volatil": False}, corr=1.0)
assert eff_full["score_ajuste"] == 56.0

# Volatil + R² nul → AUCUNE réduction de conviction (le marché ne dit rien)
eff_zero = apply_regime(70, {"regime": "neutre", "volatil": True}, corr=0.0)
assert eff_zero["score_ajuste"] == 70.0
print("✓ apply_regime pondéré : R² faible ≈ sans effet, R²=1 = plein effet")

print("\n✓ Tous les tests test_market_regime.py sont OK (hors réseau)")
