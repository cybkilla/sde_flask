# tests/test_evaluator.py — tests des règles d'évaluation multi-horizons.
#
# _juger(), _gain() et _seuil_tenir() sont des fonctions PURES extraites
# de l'évaluateur précisément pour être testables sans Supabase ni yfinance.
# La partie orchestration (requêtes, updates) reste couverte par les logs prod.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from portfolio.evaluator import _juger, _gain, _seuil_tenir, HORIZONS


# ── _seuil_tenir : élargissement en racine du temps ──
# Un cours diffuse comme √t : la tolérance TENIR doit suivre, sinon
# aucun TENIR n'est jamais "bon" à J+20.
assert _seuil_tenir(1)  == 3.0
assert _seuil_tenir(5)  == 6.7      # 3 × √5  = 6.708…
assert _seuil_tenir(20) == 13.4     # 3 × √20 = 13.416…
assert _seuil_tenir(1) < _seuil_tenir(5) < _seuil_tenir(20)
print("✓ _seuil_tenir : ±3% à J+1, élargi en √h aux horizons longs")


# ── _juger : sens directionnel par action ──
# ACHETER/RENFORCER : bon si ça monte
assert _juger("ACHETER",   +2.5, 1) is True
assert _juger("RENFORCER", -0.1, 5) is False
# VENDRE/ALLÉGER : bon si ça baisse
assert _juger("VENDRE",  -4.0, 20) is True
assert _juger("ALLÉGER", +1.2, 1)  is False
# TENIR/SURVEILLER : bon si le cours reste dans la bande (dépend de l'horizon)
assert _juger("TENIR", +5.0, 1)  is False   # 5% > seuil 3% à J+1
assert _juger("TENIR", +5.0, 20) is True    # 5% < seuil 13.4% à J+20
assert _juger("SURVEILLER", -6.0, 5) is True   # 6% < 6.7% à J+5
# Action inconnue → None (non jugeable, pas False)
assert _juger("???", 1.0, 1) is None
print("✓ _juger : sens par action, bande TENIR dépendante de l'horizon")


# ── _gain : le coût réel signé, pas le binaire ──
# ACHETER qui monte de 8% → gain +8 ; VENDRE avant une baisse de 8% → gain +8
assert _gain("ACHETER", +8.0) == 8.0
assert _gain("VENDRE",  -8.0) == 8.0
# VENDRE qui rate une hausse de 15% → coût -15 (bien plus grave qu'en rater 0.3)
assert _gain("VENDRE", +15.0) == -15.0
assert _gain("ALLÉGER", +0.3) == -0.3
# TENIR : pas de pari directionnel → pas de gain mesurable
assert _gain("TENIR", 5.0) is None
print("✓ _gain : gain/coût signé pour les conseils directionnels, None sinon")


# ── Cohérence _juger ↔ _gain : un bon conseil directionnel a un gain > 0 ──
for action in ("ACHETER", "RENFORCER", "VENDRE", "ALLÉGER"):
    for var in (-9.9, -0.1, 0.1, 9.9):
        for h in HORIZONS:
            bon, g = _juger(action, var, h), _gain(action, var)
            assert (g > 0) == bon, f"incohérence {action} var={var}"
print("✓ cohérence : bon conseil directionnel ⇔ gain positif, sur les 3 horizons")

print("\n✓ Tous les tests test_evaluator.py sont OK (hors réseau)")
