# tests/test_global_stats.py — taux directionnel de get_global_stats(), hors réseau.
#
# Mesuré en réel le 03.08.2026 sur les données de prod : le taux mélangé
# (TENIR/SURVEILLER inclus, jugés de façon asymétrique — une hausse est
# TOUJOURS un bon TENIR) affichait 85% alors que les seules décisions qui
# engagent (ACHETER/RENFORCER/VENDRE/ALLÉGER) n'étaient bonnes qu'à 60%.
# get_global_stats() doit exposer ce taux directionnel séparément, pour
# que le dashboard admin arrête de mettre en tête le chiffre gonflé.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
from portfolio.evaluator import get_global_stats

db._init = lambda: None
db.is_available = lambda: True

_ADVICE_ROWS = [
    # TENIR/SURVEILLER : toujours "bons" ici (asymétrie) -> gonflent le mélangé
    {"ticker": "TMC", "action": "TENIR",      "bon_conseil": True,  "date_conseil": "2026-08-01", "username": "admin"},
    {"ticker": "TMC", "action": "TENIR",      "bon_conseil": True,  "date_conseil": "2026-08-02", "username": "admin"},
    {"ticker": "TMC", "action": "SURVEILLER", "bon_conseil": True,  "date_conseil": "2026-08-03", "username": "admin"},
    {"ticker": "TMC", "action": "SURVEILLER", "bon_conseil": True,  "date_conseil": "2026-08-04", "username": "admin"},
    # Directionnels : mélange bon/mauvais, plus représentatif de la vraie fiabilité
    {"ticker": "FCEL", "action": "ACHETER",   "bon_conseil": True,  "date_conseil": "2026-08-01", "username": "admin"},
    {"ticker": "FCEL", "action": "RENFORCER", "bon_conseil": False, "date_conseil": "2026-08-02", "username": "admin"},
    {"ticker": "ITG",  "action": "VENDRE",    "bon_conseil": False, "date_conseil": "2026-08-01", "username": "admin"},
]


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeNot:
    def __init__(self, table):
        self._table = table

    def is_(self, col, val):
        return self._table


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self.not_ = _FakeNot(self)

    def select(self, cols):
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def table(self, name):
        if name == "daily_advice":
            return _FakeTable(list(_ADVICE_ROWS))
        if name == "positions":
            return _FakeTable([])   # aucun conseil suivi dans ce scénario
        raise AssertionError(f"table inattendue : {name}")


db._client = _FakeClient()

stats = get_global_stats()

# Mélangé : 7 conseils, 4 TENIR/SURVEILLER "bons" (asymétrie) + 1 ACHETER bon
# + 2 mauvais (RENFORCER, VENDRE) -> 5/7
assert stats["total"] == 7
assert stats["bons"] == 5
assert stats["taux_pct"] == round(5 / 7 * 100, 1)

# Directionnel : ACHETER/RENFORCER/VENDRE/ALLÉGER seulement -> 3 lignes, 1 bonne
assert stats["total_directionnel"] == 3
assert stats["bons_directionnel"] == 1
assert stats["taux_directionnel_pct"] == round(1 / 3 * 100, 1)

# Le taux directionnel doit être nettement inférieur au mélangé (c'est
# exactement le biais qu'on corrige)
assert stats["taux_directionnel_pct"] < stats["taux_pct"]
print("✓ get_global_stats : taux_directionnel_pct exclut TENIR/SURVEILLER, nettement sous le taux mélangé")


# ── Aucun conseil directionnel évalué -> None, pas 0% ni crash ──
db._client = type("FakeClient2", (), {
    "table": lambda self, name: (
        _FakeTable([{"ticker": "TMC", "action": "TENIR", "bon_conseil": True,
                     "date_conseil": "2026-08-01", "username": "admin"}])
        if name == "daily_advice" else _FakeTable([])
    ),
})()
stats2 = get_global_stats()
assert stats2["total_directionnel"] == 0
assert stats2["taux_directionnel_pct"] is None
print("✓ get_global_stats : aucun conseil directionnel évalué -> None, pas 0% trompeur")

print("\n✓ Tous les tests test_global_stats.py sont OK (hors réseau)")
