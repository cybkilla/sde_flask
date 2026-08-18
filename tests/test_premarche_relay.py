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


import pandas as pd


class _FakeYFTicker:
    def __init__(self, symbol):
        self._s = symbol

    @property
    def info(self):
        return {
            # AAA : donnée pré-marché complète ; regularMarketPreviousClose
            # est un LEURRE (4.0) — la vraie clôture doit venir de history()
            "AAA": {"preMarketPrice": 5.5, "preMarketChangePercent": 10.0,
                    "regularMarketPreviousClose": 4.0},
            "BBB": {},   # rien : marché du titre muet
            # CCC : cas réel ITG du digest 07.08.2026 — le % Yahoo (+1.9)
            # contredit ses propres prix (12.93→13.59 = +5.1%) : le gap
            # doit être RECALCULÉ depuis les prix de history(), pas
            # repris de Yahoo (ni le %, ni regularMarketPreviousClose,
            # ici aussi un leurre à 11.0)
            "CCC": {"preMarketPrice": 13.59, "preMarketChangePercent": 1.9,
                    "regularMarketPreviousClose": 11.0},
            # NAN : cas réel FCEL/TMC du 18.08.2026 — yfinance renvoie
            # parfois NaN (PAS None/absent) pour preMarketPrice. NaN est
            # truthy en Python et fait planter la sérialisation JSON
            # Supabase en aval si non filtré explicitement.
            "NAN": {"preMarketPrice": float("nan"), "preMarketChangePercent": 2.0,
                    "regularMarketPreviousClose": 9.0},
        }[self._s]

    def history(self, period="5d"):
        # Dernière clôture RÉELLE (bougie quotidienne) — DIFFÉRENTE du
        # leurre regularMarketPreviousClose ci-dessus, pour prouver que
        # c'est bien elle qui est utilisée (cas réel TMC 10.08.2026 :
        # regularMarketPreviousClose bloqué sur jeudi, history() donnait
        # la vraie clôture de vendredi). Index de vraies dates PASSÉES
        # (hier, avant-hier) : indispensable, le filtre "date < aujourd'hui"
        # ignorerait silencieusement une DataFrame sans DatetimeIndex.
        closes = {"AAA": 5.0, "BBB": 1.0, "CCC": 12.93, "NAN": 9.0}
        hier      = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        avant_hier = hier - pd.Timedelta(days=1)
        return pd.DataFrame({"Close": [closes[self._s] - 0.3, closes[self._s]]},
                            index=pd.DatetimeIndex([avant_hier, hier]))


import types
fake_yf = types.ModuleType("yfinance")
fake_yf.Ticker = _FakeYFTicker
sys.modules["yfinance"] = fake_yf

db.find = lambda table, filt: [{"ticker": "AAA"}, {"ticker": "BBB"},
                               {"ticker": "AAA"}, {"ticker": "CCC"}, {"ticker": "NAN"}]
code = relay.relayer()
assert code == 0
assert len(ecrits) == 2                      # BBB sans donnée, NAN NaN : PAS de ligne écrite
par_ticker = {e[1]: e for e in ecrits}
assert "NAN" not in par_ticker, "un preMarketPrice NaN ne doit jamais être écrit (JSON non conforme)"
table, ticker, fields, upsert = par_ticker["AAA"]
assert (table, upsert) == ("premarche_quotes", True)
assert fields["prix"] == 5.5 and fields["gap_pct"] == 10.0 and fields["prev_close"] == 5.0
assert fields["fetched_at"]                  # horodatage présent pour la péremption
ccc_fields = par_ticker["CCC"][2]
assert ccc_fields["gap_pct"] == 5.1          # (13.59/12.93 - 1) × 100, PAS le +1.9 de Yahoo
print("✓ relayer : dépôt OK, gap recalculé depuis les prix (pas le % Yahoo incohérent), "
      "sans donnée ou NaN = jamais écrit")


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

# ── Clôture veille prise dans history(), pas dans regularMarketPreviousClose ──
# Cas réel TMC 10.08.2026 : un lundi matin, regularMarketPreviousClose
# valait encore la clôture de JEUDI (4.12, leurre ici) au lieu de celle
# de VENDREDI (4.57, dans history()) — Yahoo n'avait pas fini de "rouler"
# son cache du week-end sur ce champ temps-réel.
r_aaa = get_premarket_gap("AAA")
assert r_aaa["prev_close"] == 5.0, "doit venir de history(), pas du leurre 4.0 de l'info"
assert r_aaa["gap_pct"] == round((5.5 / 5.0 - 1) * 100, 2)
print("✓ get_premarket_gap direct : clôture veille = history(), pas regularMarketPreviousClose (cas réel TMC 10.08.2026)")

# ── preMarketPrice = NaN (cas réel FCEL/TMC du 18.08.2026) -> None, jamais
#    de NaN qui remonte jusqu'à la sérialisation JSON ──
r_nan = get_premarket_gap("NAN")
assert r_nan is None, "un preMarketPrice NaN doit dégrader vers None, pas planter ou renvoyer NaN"
print("✓ get_premarket_gap direct : preMarketPrice NaN -> None, jamais de NaN qui fuit")


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

# ── _cloture_avant_aujourdhui : exclut la bougie du jour EN COURS ──
# Si le marché est ouvert au moment de l'appel, yfinance ajoute une ligne
# "aujourd'hui" mise à jour en direct — la prendre pour une "clôture"
# reviendrait à resservir le prix live sous un autre nom.
from data.market import _cloture_avant_aujourdhui

_aujourdhui = pd.Timestamp.now().normalize()
_hier       = _aujourdhui - pd.Timedelta(days=1)
_avant_hier = _hier - pd.Timedelta(days=1)

hist_avec_jour_en_cours = pd.DataFrame(
    {"Close": [4.02, 4.12, 4.60]},   # avant-hier, hier (vraie clôture), "aujourd'hui" en formation
    index=pd.DatetimeIndex([_avant_hier, _hier, _aujourdhui]),
)
assert _cloture_avant_aujourdhui(hist_avec_jour_en_cours) == 4.12
print("✓ _cloture_avant_aujourdhui : ignore la bougie du jour en cours, prend la vraie clôture d'hier")

assert _cloture_avant_aujourdhui(None) is None
assert _cloture_avant_aujourdhui(pd.DataFrame({"Close": []})) is None
hist_que_aujourdhui = pd.DataFrame({"Close": [4.60]}, index=pd.DatetimeIndex([_aujourdhui]))
assert _cloture_avant_aujourdhui(hist_que_aujourdhui) is None
print("✓ _cloture_avant_aujourdhui : historique vide ou sans séance antérieure -> None, pas de faux prix")

# Close NaN sur la séance la plus récente (cas réel TMC 18.08.2026 :
# Yahoo avait Close=NaN pour la veille, .iloc[-1] la prenait quand même
# et le NaN se propageait jusqu'à la sérialisation JSON en aval) —
# doit sauter cette ligne et prendre la dernière clôture VALIDE
_avant_avant_hier = _avant_hier - pd.Timedelta(days=1)
hist_nan_recent = pd.DataFrame(
    {"Close": [4.02, 4.12, float("nan")]},   # avant-avant-hier, avant-hier (valide), hier (NaN chez Yahoo)
    index=pd.DatetimeIndex([_avant_avant_hier, _avant_hier, _hier]),
)
assert _cloture_avant_aujourdhui(hist_nan_recent) == 4.12, \
    "doit ignorer la ligne NaN et prendre la dernière clôture valide, pas planter ni renvoyer NaN"
print("✓ _cloture_avant_aujourdhui : Close NaN sur la séance la plus récente -> ignorée, dernière clôture valide retenue")

print("\n✓ Tous les tests test_premarche_relay.py sont OK (hors réseau)")
