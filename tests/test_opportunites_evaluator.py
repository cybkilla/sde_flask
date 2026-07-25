# tests/test_opportunites_evaluator.py — évaluation multi-horizons du Top 5
# opportunités, hors réseau.
#
# _juger_horizons() est une fonction PURE (liste de flottants -> dict) —
# c'est elle qui porte toute la logique de jugement, testable sans Supabase
# ni yfinance. enregistrer_resultats()/evaluate_pending() touchent Supabase :
# on ne teste ici que leur comportement quand la base est indisponible
# (mêmes leçons que test_screener.py — jamais écrire dans la vraie base
# depuis un test).

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
db.is_available = lambda: False   # ces tests ne doivent jamais toucher Supabase

from analysis import opportunites_evaluator as oe


# ── _juger_horizons : cas nominal, tous les horizons disponibles ──
closes = [105.0] + [110.0] * 4 + [90.0] * 15   # J+1 monte, J+5 monte, J+20 baisse
update = oe._juger_horizons(100.0, closes, deja={})
assert update["prix_j1"] == 105.0
assert update["variation_j1"] == 5.0
assert update["bon_j1"] is True
assert update["variation_j5"] == 10.0
assert update["bon_j5"] is True
assert update["variation_j20"] == -10.0
assert update["bon_j20"] is False
print("✓ _juger_horizons : bon = le prix a monté, peu importe l'ampleur")


# ── Pas assez de séances écoulées -> horizon absent, pas de crash ──
update = oe._juger_horizons(100.0, [102.0, 103.0], deja={})
assert "prix_j1" in update and "prix_j5" not in update and "prix_j20" not in update
print("✓ _juger_horizons : horizons non encore observables simplement absents")


# ── Horizon déjà évalué -> ignoré même si les données sont dispo ──
update = oe._juger_horizons(100.0, closes, deja={1: True})
assert "prix_j1" not in update
assert "prix_j5" in update
print("✓ _juger_horizons : n'écrase jamais un horizon déjà évalué")


# ── enregistrer_resultats : silencieux (pas de crash) si Supabase indispo ──
oe.enregistrer_resultats([{"ticker": "AAA", "prix": 10.0, "score_global": 55}])
oe.enregistrer_resultats([])   # liste vide -> rien à faire
oe.enregistrer_resultats([{"ticker": "SANSPRIX"}])   # pas de prix -> ignoré, pas de crash
print("✓ enregistrer_resultats : robuste (Supabase indisponible, liste vide, prix manquant)")

print("\n✓ Tous les tests test_opportunites_evaluator.py sont OK (hors réseau)")
