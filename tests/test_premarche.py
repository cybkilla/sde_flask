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
    "CCC": {"price": 9.1, "prev_close": 9.0},   # prix de secours -> affiché quand même
    "DDD": {},                                   # rien du tout -> exclu
}.get(t, {})
positions_mod.get_portfolio_summary = lambda u, t, prix: (
    None if prix is None else
    {"currency": "USD", "position_fermee": False, "pnl_pct": 5.0}
)

etats = premarche.etat_premarche("admin")

# DDD exclu (aucune donnée, même de secours) ; CCC présent malgré l'absence
# de vraie donnée pré-marché (demande utilisateur du 31.07.2026)
assert [e["ticker"] for e in etats] == ["AAA", "BBB", "CCC"], etats
print("✓ etat_premarche : ticker sans AUCUNE donnée exclu, mais affiché s'il y a un prix de secours")

# Trié par |gap| décroissant -> AAA (10%) avant BBB (1%) avant CCC (inconnu, traité comme 0)
assert etats[0]["ticker"] == "AAA"
assert etats[0]["notable"] is True    # 10% > seuil fixe 3% (pas d'ATR)
assert etats[1]["ticker"] == "BBB"
assert etats[1]["notable"] is False   # 1% < 3%
print("✓ etat_premarche : trié par |gap| décroissant, notable = gap_significatif()")

# CCC : gap_pct=None explicite (jamais un gap inventé), notable toujours False
ccc = next(e for e in etats if e["ticker"] == "CCC")
assert ccc["gap_pct"] is None
assert ccc["notable"] is False
assert ccc["prix"] == 9.1 and ccc["prev_close"] == 9.0
print("✓ etat_premarche : sans vraie donnée pré-marché -> gap_pct=None, jamais inventé")


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

print("\n✓ Tous les tests test_premarche.py sont OK (hors réseau)")
