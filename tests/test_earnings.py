# tests/test_earnings.py — get_next_earnings(), hors réseau.
#
# Demandé le 03.08.2026 : un choc résultats (ex. MXL -21.2% le lendemain
# d'un ACHETER à score 65.5) est un événement à variance élevée qu'aucun
# signal technique/fondamental ne peut anticiper. Finnhub expose un
# calendrier d'earnings filtrable par ticker, gratuit — vérifié en réel
# le même jour (TMC : deux dates renvoyées, 13 et 17.08.2026).
#
# Étendu le 14.08.2026 : demande utilisateur pour un résumé succinct une
# fois les résultats publiés (cas réel TMC : -8% le lendemain d'un BPA
# -0.14$ vs -0.06$ attendu). epsActual se remplit tout seul dans
# earnings_calendar une fois publié — vérifié en réel le même jour,
# mêmes chiffres que company_earnings (surprisePercent -131.02%).

import sys, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import data.market as market_mod
from data.market import get_next_earnings, get_next_earnings_bulk

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
    {"symbol": "TMC", "date": d1, "quarter": 2, "year": 2026, "epsEstimate": -0.06, "epsActual": None},
    {"symbol": "TMC", "date": d2, "quarter": 2, "year": 2026, "epsEstimate": -0.06, "epsActual": None},
])
r = get_next_earnings("TMC")
assert r == {"date": d2, "jours": 6, "statut": "a_venir"}
print("✓ get_next_earnings : plusieurs dates renvoyées -> la plus proche est retenue")


# ── Résultats publiés HIER (cas réel TMC 14.08.2026) -> statut "publie",
#    BPA réel/estimé/surprise, formule vérifiée contre company_earnings ──
d_hier = str(_TODAY - datetime.timedelta(days=1))
market_mod._fh = lambda: _FakeFinnhub([
    {"symbol": "TMC", "date": d_hier, "quarter": 2, "year": 2026,
     "epsEstimate": -0.0606, "epsActual": -0.14},
])
r_publie = get_next_earnings("TMC")
assert r_publie["statut"] == "publie"
assert r_publie["jours"] == -1
assert r_publie["eps_estimate"] == -0.0606 and r_publie["eps_actual"] == -0.14
assert r_publie["surprise_pct"] == round((-0.14 - -0.0606) / abs(-0.0606) * 100, 1)  # ≈ -131.0
print(f"✓ get_next_earnings : résultats publiés -> statut 'publie', "
      f"surprise {r_publie['surprise_pct']}% (cas réel TMC, cohérent avec company_earnings)")

# ── Publié mais SANS estimate (ticker peu couvert) -> surprise_pct None,
#    pas de division par zéro/None ──
market_mod._fh = lambda: _FakeFinnhub([
    {"symbol": "XYZ", "date": d_hier, "quarter": 1, "year": 2026,
     "epsEstimate": None, "epsActual": 0.10},
])
r_sans_est = get_next_earnings("XYZ")
assert r_sans_est["statut"] == "publie"
assert r_sans_est["surprise_pct"] is None
print("✓ get_next_earnings : publié sans estimate connu -> surprise_pct None, pas de crash")

# ── Annoncé aujourd'hui mais pas encore de epsActual (résultat pas
#    encore traité par Finnhub) -> reste "a_venir", pas un faux "publie" ──
market_mod._fh = lambda: _FakeFinnhub([
    {"symbol": "TMC", "date": str(_TODAY), "quarter": 2, "year": 2026,
     "epsEstimate": -0.06, "epsActual": None},
])
r_pas_encore = get_next_earnings("TMC")
assert r_pas_encore["statut"] == "a_venir"
print("✓ get_next_earnings : annoncé sans epsActual encore connu -> reste 'a_venir'")


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

# ── get_next_earnings_bulk : UN appel Finnhub (sans filtre symbol) pour
#    plusieurs tickers — demandé le 10.08.2026, badge dédié sur
#    /portfolio/overview (évite le N+1 déjà rencontré ailleurs) ──
class _FakeFinnhubGlobal:
    def __init__(self, rows):
        self._rows = rows

    def earnings_calendar(self, _from, to, symbol):
        assert symbol == ""   # calendrier global, filtré en Python ensuite
        return {"earningsCalendar": self._rows}


d_tmc  = str(_TODAY + datetime.timedelta(days=6))
d_fcel = str(_TODAY + datetime.timedelta(days=2))
market_mod._fh = lambda: _FakeFinnhubGlobal([
    {"symbol": "AAPL", "date": str(_TODAY + datetime.timedelta(days=1))},  # pas dans nos tickers
    {"symbol": "TMC",  "date": d_tmc,  "epsEstimate": -0.06, "epsActual": None},
    {"symbol": "FCEL", "date": d_fcel, "epsEstimate": None,  "epsActual": None},
])
res = get_next_earnings_bulk(["TMC", "FCEL", "ITG"])
assert res == {"TMC": {"date": d_tmc, "jours": 6, "statut": "a_venir"},
               "FCEL": {"date": d_fcel, "jours": 2, "statut": "a_venir"}}
assert "ITG" not in res and "AAPL" not in res
print("✓ get_next_earnings_bulk : un seul appel Finnhub, filtré sur nos tickers, absents si rien sous l'horizon")

# ── Résultats publiés dans le lot -> statut "publie" transmis pour ce ticker ──
market_mod._fh = lambda: _FakeFinnhubGlobal([
    {"symbol": "TMC", "date": d_hier, "quarter": 2, "year": 2026,
     "epsEstimate": -0.0606, "epsActual": -0.14},
])
res_publie = get_next_earnings_bulk(["TMC"])
assert res_publie["TMC"]["statut"] == "publie"
assert res_publie["TMC"]["eps_actual"] == -0.14
print("✓ get_next_earnings_bulk : statut 'publie' transmis correctement dans le lot")

# ── Aucun ticker -> {} sans appel réseau ──
market_mod._fh = lambda: (_ for _ in ()).throw(RuntimeError("ne doit jamais être appelé"))
assert get_next_earnings_bulk([]) == {}
print("✓ get_next_earnings_bulk : aucun ticker -> {} sans appeler Finnhub")

# ── Finnhub indisponible -> {} sans crash ──
market_mod._fh = _boom
assert get_next_earnings_bulk(["TMC"]) == {}
print("✓ get_next_earnings_bulk : Finnhub indisponible -> {} sans crash")

print("\n✓ Tous les tests test_earnings.py sont OK (hors réseau)")
