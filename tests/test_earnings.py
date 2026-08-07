# tests/test_earnings.py — get_next_earnings(), hors réseau.
#
# Demandé le 03.08.2026 : un choc résultats (ex. MXL -21.2% le lendemain
# d'un ACHETER à score 65.5) est un événement à variance élevée qu'aucun
# signal technique/fondamental ne peut anticiper. Finnhub expose un
# calendrier d'earnings filtrable par ticker, gratuit — vérifié en réel
# le même jour (TMC : deux dates renvoyées, 13 et 17.08.2026).

import sys, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import data.market as market_mod
from data.market import get_next_earnings

_TODAY = datetime.date.today()


class _FakeFinnhub:
    def __init__(self, rows):
        self._rows = rows

    def earnings_calendar(self, _from, to, symbol):
        assert symbol != ""   # toujours filtré par ticker, jamais le calendrier global
        return {"earningsCalendar": self._rows}


# ── Deux dates renvoyées (cas réel TMC) -> la plus proche est retenue ──
d1 = str(_TODAY + datetime.timedelta(days=10))
d2 = str(_TODAY + datetime.timedelta(days=6))
market_mod._fh = lambda: _FakeFinnhub([
    {"symbol": "TMC", "date": d1, "quarter": 2, "year": 2026},
    {"symbol": "TMC", "date": d2, "quarter": 2, "year": 2026},
])
r = get_next_earnings("TMC")
assert r == {"date": d2, "jours": 6}
print("✓ get_next_earnings : plusieurs dates renvoyées -> la plus proche est retenue")


# ── Aucune date connue -> None, pas de crash ──
market_mod._fh = lambda: _FakeFinnhub([])
assert get_next_earnings("FCEL") is None
print("✓ get_next_earnings : aucune date connue -> None")


# ── Finnhub indisponible -> None, dégradation silencieuse ──
def _boom():
    raise RuntimeError("Finnhub down")
market_mod._fh = _boom
assert get_next_earnings("ITG") is None
print("✓ get_next_earnings : Finnhub indisponible -> None, jamais bloquant")

print("\n✓ Tous les tests test_earnings.py sont OK (hors réseau)")
