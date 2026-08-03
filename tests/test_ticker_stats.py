# tests/test_ticker_stats.py — get_ticker_stats_bulk(), hors réseau.
#
# Demandé le 03.08.2026 : afficher sur CHAQUE position la fiabilité J+1 des
# conseils déjà émis pour ce ticker précis (pas la stat globale admin, qui
# mélange tous les utilisateurs). Une seule requête groupée par utilisateur
# + liste de tickers — même souci de perf que get_all_today_advice.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
from portfolio.evaluator import get_ticker_stats_bulk

db._init = lambda: None
db.is_available = lambda: True

_ROWS = [
    {"ticker": "TMC", "bon_conseil": True,  "bon_conseil_j20": False},
    {"ticker": "TMC", "bon_conseil": True,  "bon_conseil_j20": True},
    {"ticker": "TMC", "bon_conseil": False, "bon_conseil_j20": None},
    {"ticker": "TMC", "bon_conseil": True,  "bon_conseil_j20": None},
    {"ticker": "FCEL", "bon_conseil": False, "bon_conseil_j20": None},
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

    def eq(self, col, val):
        assert col == "username"
        return self

    def in_(self, col, tickers):
        assert col == "ticker"
        self._rows = [r for r in self._rows if r["ticker"] in tickers]
        return self

    def execute(self):
        return _FakeResult(self._rows)


db._client = type("FakeClient", (), {
    "table": lambda self, name: _FakeTable(list(_ROWS)),
})()

stats = get_ticker_stats_bulk("admin", ["TMC", "FCEL", "ITG"])
assert stats["TMC"] == {"total": 4, "bons": 3, "taux_pct": 75.0,
                        "total_j20": 2, "bons_j20": 1, "taux_j20_pct": 50.0}
assert stats["FCEL"] == {"total": 1, "bons": 0, "taux_pct": 0.0,
                         "total_j20": 0, "bons_j20": 0, "taux_j20_pct": None}
assert "ITG" not in stats   # aucun conseil évalué pour ce ticker -> absent, pas 0%
print("✓ get_ticker_stats_bulk : regroupement par ticker, taux_pct/taux_j20_pct corrects, ticker sans historique absent")


# ── Pas de Supabase / pas de tickers -> dégradation silencieuse ──
db.is_available = lambda: False
assert get_ticker_stats_bulk("admin", ["TMC"]) == {}
db.is_available = lambda: True
assert get_ticker_stats_bulk("admin", []) == {}
print("✓ get_ticker_stats_bulk : Supabase indisponible ou aucun ticker -> {} sans crash")

print("\n✓ Tous les tests test_ticker_stats.py sont OK (hors réseau)")
