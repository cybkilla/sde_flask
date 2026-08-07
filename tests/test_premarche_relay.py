# tests/test_premarche_relay.py — relais pré-marché GitHub Actions, hors réseau.
#
# Mis en place le 07.08.2026 : yfinance (seule source gratuite d'un vrai
# prix pré-marché) est bloqué depuis les IP Render — une GitHub Action le
# fait tourner ailleurs et dépose les prix dans premarche_quotes.
# Ici on teste les DEUX bouts de la chaîne, réseau et Supabase mockés :
#   - lecteur : get_premarket_gap() lit le relais en premier, exige la
#     fraîcheur (≤ 45 min), retombe sur yfinance direct sinon
#   - écrivain : relayer() n'écrit jamais de ligne sans vraie donnée

import sys, pathlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
import utils.net_timeout as nt
from data.market import get_premarket_gap

db._init = lambda: None
db.is_available = lambda: True

# yfinance direct neutralisé : with_timeout lève -> le chemin 2 rend None.
# (Patch au niveau du module utils.net_timeout : data/market.py fait
# l'import DANS la fonction, il récupère donc l'attribut patché.)
def _pas_de_reseau(*a, **k):
    raise RuntimeError("réseau coupé dans les tests")
nt.with_timeout = _pas_de_reseau


# ── Ligne relais fraîche -> retournée telle quelle, sans toucher yfinance ──
_now = datetime.now(timezone.utc)
db.find_one = lambda table, filt: {
    "ticker": "TMC", "prix": 3.62, "gap_pct": -1.09, "prev_close": 3.66,
    "fetched_at": (_now - timedelta(minutes=10)).isoformat(),
}
r = get_premarket_gap("TMC")
assert r == {"prix": 3.62, "gap_pct": -1.09, "prev_close": 3.66}
print("✓ get_premarket_gap : ligne relais fraîche (10 min) servie sans appel yfinance")


# ── Ligne périmée (> 45 min) -> ignorée, repli yfinance (coupé ici) -> None ──
db.find_one = lambda table, filt: {
    "ticker": "TMC", "prix": 3.62, "gap_pct": -1.09, "prev_close": 3.66,
    "fetched_at": (_now - timedelta(minutes=90)).isoformat(),
}
assert get_premarket_gap("TMC") is None
print("✓ get_premarket_gap : ligne relais périmée (90 min) ignorée — pas de vieux prix resservi")


# ── Pas de ligne relais / Supabase indisponible -> repli direct, pas de crash ──
db.find_one = lambda table, filt: None
assert get_premarket_gap("FCEL") is None
db.is_available = lambda: False
assert get_premarket_gap("FCEL") is None
db.is_available = lambda: True
print("✓ get_premarket_gap : sans relais ni yfinance -> None, dégradation propre")


# ── Écrivain : relayer() n'écrit que les tickers avec une vraie donnée ──
from scripts import premarche_relay as relay

relay._fenetre_premarche_paris = lambda: True
db.find = lambda table, filt: [{"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "AAA"}]

ecrits = []
db.update_one = lambda table, filt, update, upsert=False: ecrits.append(
    (table, filt["ticker"], update["$set"], upsert))


class _FakeYFTicker:
    def __init__(self, symbol):
        self._s = symbol

    @property
    def info(self):
        return {
            # AAA : donnée pré-marché complète ; BBB : rien (marché du titre muet)
            "AAA": {"preMarketPrice": 5.5, "preMarketChangePercent": 10.0,
                    "regularMarketPreviousClose": 5.0},
            "BBB": {},
        }[self._s]


import types
fake_yf = types.ModuleType("yfinance")
fake_yf.Ticker = _FakeYFTicker
sys.modules["yfinance"] = fake_yf

code = relay.relayer()
assert code == 0
assert len(ecrits) == 1                      # BBB sans donnée : PAS de ligne écrite
table, ticker, fields, upsert = ecrits[0]
assert (table, ticker, upsert) == ("premarche_quotes", "AAA", True)
assert fields["prix"] == 5.5 and fields["gap_pct"] == 10.0 and fields["prev_close"] == 5.0
assert fields["fetched_at"]                  # horodatage présent pour la péremption
print("✓ relayer : ticker AAA déposé (upsert), BBB sans donnée jamais écrit, doublons dédupliqués")


# ── Hors fenêtre pré-marché -> sortie immédiate, aucun accès réseau/DB ──
relay._fenetre_premarche_paris = lambda: False
db.find = _pas_de_reseau   # tout accès ferait planter le test
assert relay.relayer() == 0
print("✓ relayer : hors fenêtre (10h00-15h25 Paris) -> sortie immédiate sans rien toucher")

print("\n✓ Tous les tests test_premarche_relay.py sont OK (hors réseau)")
