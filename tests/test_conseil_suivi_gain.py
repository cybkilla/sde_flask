# tests/test_conseil_suivi_gain.py — get_conseil_suivi_gain_bulk(), hors réseau.
#
# Demandé le 03.08.2026 : "si j'avais suivi le conseil de renforcer 2
# actions, est-ce que j'aurais été gagnant ou pas". Remonte l'historique
# daily_advice jusqu'au premier jour de la série d'action EN COURS (pas
# tout l'historique du ticker) et compare au prix live via _gain(), la
# même logique signée que l'évaluation J+1/5/20.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
from portfolio.evaluator import get_conseil_suivi_gain_bulk

db._init = lambda: None
db.is_available = lambda: True


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, cols):
        return self

    def eq(self, col, val):
        return self

    def in_(self, col, tickers):
        self._rows = [r for r in self._rows if r["ticker"] in tickers]
        return self

    def order(self, col, desc=False):
        self._rows = sorted(self._rows, key=lambda r: r[col], reverse=desc)
        return self

    def execute(self):
        return _FakeResult(self._rows)


# TMC : RENFORCER depuis le 02/08 (avant : ACHETER le 30/07, cassure de série)
# -> "depuis" doit être le 02/08 (prix 3.45), pas le 30/07.
# FCEL : VENDRE en cours depuis le 01/08 -> gain si le prix a baissé.
# ITG  : TENIR -> aucune transaction, absent du résultat.
# GGG  : RENFORCER mais pas de prix live -> absent (rien à comparer).
_ROWS = [
    {"ticker": "TMC", "date_conseil": "2026-07-30", "action": "ACHETER",   "prix_jour": 3.20},
    {"ticker": "TMC", "date_conseil": "2026-08-02", "action": "RENFORCER", "prix_jour": 3.45},
    {"ticker": "TMC", "date_conseil": "2026-08-03", "action": "RENFORCER", "prix_jour": 3.50},
    {"ticker": "FCEL", "date_conseil": "2026-08-01", "action": "VENDRE",   "prix_jour": 20.0},
    {"ticker": "FCEL", "date_conseil": "2026-08-03", "action": "VENDRE",   "prix_jour": 19.5},
    {"ticker": "ITG", "date_conseil": "2026-08-03", "action": "TENIR",     "prix_jour": 11.0},
    {"ticker": "GGG", "date_conseil": "2026-08-03", "action": "RENFORCER", "prix_jour": 5.0},
]

db._client = type("FakeClient", (), {
    "table": lambda self, name: _FakeTable(list(_ROWS)),
})()

prix_actuels = {"TMC": 3.85, "FCEL": 18.0, "ITG": 11.5}   # pas de prix pour GGG
resultat = get_conseil_suivi_gain_bulk("admin", ["TMC", "FCEL", "ITG", "GGG"], prix_actuels)

# TMC : depuis le 02/08 (début de la série RENFORCER, pas le 30/07 ACHETER)
tmc = resultat["TMC"]
assert tmc["depuis"] == "2026-08-02"
assert tmc["prix_depart"] == 3.45
assert tmc["gain_pct"] == round((3.85 - 3.45) / 3.45 * 100, 2)   # ACHETER-like -> gain = +variation
print("✓ get_conseil_suivi_gain_bulk : remonte au 1er jour de la série d'action EN COURS, pas tout l'historique")

# FCEL : VENDRE depuis le 01/08, prix a baissé (20.0 -> 18.0) -> gain positif (baisse évitée)
fcel = resultat["FCEL"]
assert fcel["depuis"] == "2026-08-01"
var_fcel = round((18.0 - 20.0) / 20.0 * 100, 2)
assert fcel["gain_pct"] == round(-var_fcel, 2)
assert fcel["gain_pct"] > 0
print("✓ get_conseil_suivi_gain_bulk : VENDRE suivi d'une baisse -> gain positif (perte évitée)")

# ITG (TENIR) et GGG (pas de prix live) -> absents, pas de faux calcul
assert "ITG" not in resultat
assert "GGG" not in resultat
print("✓ get_conseil_suivi_gain_bulk : TENIR/SURVEILLER exclus (pas de transaction), ticker sans prix live exclu")

# ── Pas de Supabase / pas de tickers -> dégradation silencieuse ──
db.is_available = lambda: False
assert get_conseil_suivi_gain_bulk("admin", ["TMC"], prix_actuels) == {}
db.is_available = lambda: True
assert get_conseil_suivi_gain_bulk("admin", [], prix_actuels) == {}
print("✓ get_conseil_suivi_gain_bulk : Supabase indisponible ou aucun ticker -> {} sans crash")

print("\n✓ Tous les tests test_conseil_suivi_gain.py sont OK (hors réseau)")
