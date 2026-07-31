# tests/test_premarche.py — état pré-marché des positions, hors réseau.
#
# Demandé le 31.07.2026 : "se préparer à ce qui va arriver au cours de la
# séance à venir". etat_premarche() est testée avec toutes ses
# dépendances réseau monkeypatchées (même pattern que
# test_portfolio_history.py) ; gap_significatif() elle-même est déjà
# testée en détail dans test_risk.py, réutilisée ici telle quelle.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
import portfolio.positions as positions_mod
import data.market as market_mod
import snapshot as snapshot_mod
from portfolio import premarche

positions_mod.get_positions = lambda u: [
    {"ticker": "AAA", "type": "achat", "quantite": 10, "prix_achat": 5.0,
     "currency": "USD", "company": "AAA Inc."},
    {"ticker": "BBB", "type": "achat", "quantite": 5,  "prix_achat": 20.0,
     "currency": "USD", "company": "BBB Corp."},
    {"ticker": "CCC", "type": "achat", "quantite": 3,  "prix_achat": 9.0,
     "currency": "USD", "company": "CCC Ltd."},
    {"ticker": "DDD", "type": "achat", "quantite": 1,  "prix_achat": 1.0,
     "currency": "USD", "company": "DDD SA"},
]
snapshot_mod.get_snapshot = lambda t, max_age_hours=24: None   # pas d'ATR -> seuil fixe 3%
market_mod.get_premarket_gap = lambda t: {
    "AAA": {"prix": 5.5, "prev_close": 5.0, "gap_pct": 10.0},   # gap notable (>3%)
    "BBB": {"prix": 20.2, "prev_close": 20.0, "gap_pct": 1.0},  # gap dans le bruit
    "CCC": None,   # pas de vraie donnée pré-marché (cas fréquent, yfinance bloqué sur Render)
    "DDD": None,   # idem, ET pas de prix de secours -> vraiment rien à montrer
}[t]
market_mod.get_live_price = lambda t: {
    # Finnhub hors séance : "price" (c) EST la vraie clôture de la veille
    # (J-1), "prev_close" (pc) est la clôture d'AVANT (J-2) — vérifié en
    # réel le 31.07.2026 sur ITG (timestamp du quote = clôture de la
    # veille). _donnees_brutes ne doit reprendre QUE "price" comme
    # clôture veille, jamais "prev_close" (ce serait J-2) ni l'utiliser
    # comme un "prix pré-marché" (ça n'en est pas un).
    "CCC": {"price": 9.1, "prev_close": 9.9},   # 9.1 = vraie clôture veille ; 9.9 = J-2, ignoré
    "DDD": {},                                   # rien du tout -> exclu
}.get(t, {})
positions_mod.get_portfolio_summary = lambda u, t, prix: (
    None if prix is None else
    {"currency": "USD", "position_fermee": False, "pnl_pct": 5.0}
)

etats = premarche.etat_premarche("admin")

# DDD exclu (aucune donnée, même de secours) ; CCC présent malgré l'absence
# de vrai prix pré-marché (demande utilisateur du 31.07.2026)
assert [e["ticker"] for e in etats] == ["AAA", "BBB", "CCC"], etats
print("✓ etat_premarche : ticker sans AUCUNE donnée exclu, mais affiché (clôture veille) s'il y a un prix de secours")

# Trié par |gap| décroissant -> AAA (10%) avant BBB (1%) avant CCC (pas de gap)
assert etats[0]["ticker"] == "AAA"
assert etats[0]["notable"] is True    # 10% confirmé > seuil fixe 3% (pas d'ATR)
assert etats[0]["confirme"] is True
assert etats[1]["ticker"] == "BBB"
assert etats[1]["notable"] is False   # 1% < 3%
print("✓ etat_premarche : trié par |gap| décroissant, notable = gap_significatif() si confirmé")

# CCC : PAS de prix pré-marché (prix=None, jamais inventé), clôture veille
# = "price" de get_live_price (9.1, la vraie clôture J-1) — PAS
# "prev_close" (9.9, qui serait J-2). Pas de gap calculable sans un vrai
# prix pré-marché à comparer (calculer un % entre J-1 et J-2 serait
# justement l'ancien bug : la variation de la veille, pas un gap
# pré-marché) — jamais notable, donc jamais de quoi déclencher l'email.
ccc = next(e for e in etats if e["ticker"] == "CCC")
assert ccc["prix"] is None
assert ccc["prev_close"] == 9.1
assert ccc["gap_pct"] is None
assert ccc["confirme"] is False
assert ccc["notable"] is False
print("✓ etat_premarche : sans vrai prix pré-marché -> clôture veille correcte (J-1), pas de gap inventé")


# ── Position fermée -> exclue ──
positions_mod.get_portfolio_summary = lambda u, t, prix: (
    None if prix is None else
    {"currency": "USD", "position_fermee": (t == "AAA"), "pnl_pct": 5.0}
)
etats2 = premarche.etat_premarche("admin")
assert "AAA" not in [e["ticker"] for e in etats2]
assert "BBB" in [e["ticker"] for e in etats2]
print("✓ etat_premarche : position clôturée exclue")


# ── Anti-doublon email : lecture/écriture sur users.premarche_digest_date ──
db.is_available = lambda: False
assert premarche.deja_envoye_aujourdhui("admin") is False   # dégradation silencieuse
premarche.marquer_envoye("admin")                            # ne doit pas crasher sans Supabase

db.is_available = lambda: True
from datetime import date
db.find_one = lambda table, filt: {"premarche_digest_date": str(date.today())}
assert premarche.deja_envoye_aujourdhui("admin") is True

db.find_one = lambda table, filt: {"premarche_digest_date": "2020-01-01"}
assert premarche.deja_envoye_aujourdhui("admin") is False

sauvegardes = []
db.update_one = lambda table, filt, update, upsert=False: sauvegardes.append((table, filt, update))
premarche.marquer_envoye("admin")
assert sauvegardes == [("users", {"username": "admin"},
                        {"$set": {"premarche_digest_date": str(date.today())}})]
print("✓ deja_envoye_aujourdhui / marquer_envoye : anti-doublon 1x/jour sur users")

# ── Récupération EN PARALLÈLE, pas séquentielle ──
# Signalé 31.07.2026 : "Chargement des positions" resté bloqué longtemps —
# cause réelle : chaque appel réseau peut prendre plusieurs secondes, et en
# séquence sur N positions ça bloquait le seul worker gunicorn (sync,
# mono-worker) jusqu'à N fois ce délai. Vérifié ici avec un faux appel
# lent (0.3s) sur 5 tickers : en séquence ça ferait ~1.5s, en parallèle
# ~0.3-0.6s — la marge (< 1s) suffit à distinguer les deux sans rendre le
# test fragile sur une machine chargée.
import time
positions_mod.get_positions = lambda u: [
    {"ticker": f"T{i}", "type": "achat", "quantite": 1, "prix_achat": 1.0,
     "currency": "USD", "company": f"T{i} Inc."}
    for i in range(5)
]


def _gap_lent(t):
    time.sleep(0.3)
    return {"prix": 10.0, "prev_close": 9.5, "gap_pct": 5.0}


market_mod.get_premarket_gap = _gap_lent
positions_mod.get_portfolio_summary = lambda u, t, prix: (
    {"currency": "USD", "position_fermee": False, "pnl_pct": 0.0}
)

t0 = time.time()
etats_par = premarche.etat_premarche("admin")
duree = time.time() - t0
assert len(etats_par) == 5
assert duree < 1.0, f"attendu < 1s en parallèle (5 x 0.3s), obtenu {duree:.2f}s"
print(f"✓ etat_premarche : 5 tickers à 0.3s chacun récupérés en {duree:.2f}s (parallèle, pas 1.5s en séquence)")

print("\n✓ Tous les tests test_premarche.py sont OK (hors réseau)")
