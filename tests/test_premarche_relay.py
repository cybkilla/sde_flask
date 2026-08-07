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
            # CCC : cas réel ITG du digest 07.08.2026 — le % Yahoo (+1.9)
            # contredit ses propres prix (12.93→13.59 = +5.1%) : le gap
            # doit être RECALCULÉ depuis les prix, pas repris de Yahoo
            "CCC": {"preMarketPrice": 13.59, "preMarketChangePercent": 1.9,
                    "regularMarketPreviousClose": 12.93},
        }[self._s]


import types
fake_yf = types.ModuleType("yfinance")
fake_yf.Ticker = _FakeYFTicker
sys.modules["yfinance"] = fake_yf

db.find = lambda table, filt: [{"ticker": "AAA"}, {"ticker": "BBB"},
                               {"ticker": "AAA"}, {"ticker": "CCC"}]
code = relay.relayer()
assert code == 0
assert len(ecrits) == 2                      # BBB sans donnée : PAS de ligne écrite
par_ticker = {e[1]: e for e in ecrits}
table, ticker, fields, upsert = par_ticker["AAA"]
assert (table, upsert) == ("premarche_quotes", True)
assert fields["prix"] == 5.5 and fields["gap_pct"] == 10.0 and fields["prev_close"] == 5.0
assert fields["fetched_at"]                  # horodatage présent pour la péremption
ccc_fields = par_ticker["CCC"][2]
assert ccc_fields["gap_pct"] == 5.1          # (13.59/12.93 - 1) × 100, PAS le +1.9 de Yahoo
print("✓ relayer : dépôt OK, gap recalculé depuis les prix (pas le % Yahoo incohérent), sans donnée = jamais écrit")


# ── Secrets manquants/invalides -> échec BRUYANT (run rouge), pas silence vert ──
# Premier run réel 07.08.2026 : 27s, vert, table vide — aucun indice en logs.
db.is_available = lambda: False
assert relay.relayer() == 1
db.is_available = lambda: True
print("✓ relayer : Supabase inaccessible -> code retour 1 (voyant rouge côté GitHub)")


# ── Lecteur, chemin yfinance direct : même recalcul du gap ──
nt.with_timeout = lambda fn, secs: fn()      # réseau "rétabli" -> le fake yfinance répond
db.find_one = lambda table, filt: None       # pas de ligne relais -> chemin direct
r_direct = get_premarket_gap("CCC")
assert r_direct == {"prix": 13.59, "gap_pct": 5.1, "prev_close": 12.93}
print("✓ get_premarket_gap direct : gap recalculé depuis les prix affichés (cas réel ITG +1.9% -> +5.1%)")


# ── Hors fenêtre pré-marché -> sortie immédiate, aucun accès réseau/DB ──
relay._fenetre_premarche_paris = lambda: False
db.find = _pas_de_reseau   # tout accès ferait planter le test
assert relay.relayer() == 0
print("✓ relayer : hors fenêtre (10h00-15h25 Paris) -> sortie immédiate sans rien toucher")


# ── RELAY_FORCE=true (test manuel) -> la fenêtre est ignorée ──
# Ajouté après le premier test réel du 07.08.2026, lancé à 15h50 Paris :
# fenêtre fermée -> impossible de valider les secrets sans attendre lundi.
import os
os.environ["RELAY_FORCE"] = "true"
db.find = lambda table, filt: [{"ticker": "AAA"}]
ecrits.clear()
assert relay.relayer() == 0
assert len(ecrits) == 1 and ecrits[0][1] == "AAA"
del os.environ["RELAY_FORCE"]
print("✓ relayer : RELAY_FORCE=true ignore la fenêtre (validation manuelle de la chaîne complète)")

print("\n✓ Tous les tests test_premarche_relay.py sont OK (hors réseau)")
