# tests/test_portfolio_history.py — snapshot_si_du(), hors réseau.
#
# Le graphe "Évolution du portefeuille" restait figé des jours entiers
# quand personne n'ouvrait /portfolio après 22h Paris (le seul déclencheur
# avant le 28.07.2026). snapshot_si_du() doit pouvoir tourner seule depuis
# le scheduler — tout ce qui touche réseau/Supabase est monkeypatché ici.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
from portfolio import history
import portfolio.positions as positions_mod
import data.market as market_mod

_real_save_daily_snapshot = history.save_daily_snapshot   # gardé avant l'override ci-dessous


# ── save_daily_snapshot : le cash affiché doit inclure la correction admin,
#    pas seulement le calcul par lots — même bug que sur portfolio.html
#    (28.07.2026) : un cash corrigé à 10$ restait affiché à l'ancienne
#    valeur, ici la logique de recalcul par lots ignorait totalement
#    positions.py::get_cash_disponible() ──
db._init = lambda: None
db.is_available = lambda: True
upserts = []
db._client = type("FakeClient", (), {
    "table": lambda self, name: type("FakeTable", (), {
        "upsert": lambda self, rows, on_conflict=None: (upserts.append(rows) or self),
        "execute": lambda self: None,
    })()
})()

positions_mod.get_positions   = lambda u: [{"ticker": "AAA", "type": "achat", "quantite": 1,
                                            "prix_achat": 10.0, "currency": "USD"}]  # solde brut = -10
positions_mod.get_ajustement_cash = lambda u: 60.0   # correction admin : +60 -> cash réel 50

positions_fake = [{"currency": "USD", "summary": {
    "position_fermee": False, "valeur_actuelle": 100.0, "pnl_euros": 0,
    "lots": [{"type": "achat", "quantite": 1, "prix_achat": 10.0}],
}}]
assert _real_save_daily_snapshot("admin", positions_fake) is True
assert len(upserts) == 1
row = upserts[0][0]
assert row["cash_dispo"] == 50.0, f"attendu 50.0 (corrigé), obtenu {row['cash_dispo']}"
print("✓ save_daily_snapshot : le cash inclut la correction admin (get_cash_disponible), pas juste les lots")


sauvegardes = []
history.save_daily_snapshot = lambda username, positions: (
    sauvegardes.append((username, positions)) or True
)


def _reset(marche_ferme=True, deja_fait=False):
    sauvegardes.clear()
    history._market_closed_today = lambda: marche_ferme
    history.snapshot_exists_today = lambda u: deja_fait


# ── Marché pas encore fermé -> pas de snapshot, pas d'appel réseau ──
_reset(marche_ferme=False)
assert history.snapshot_si_du("admin") is False
assert sauvegardes == []
print("✓ snapshot_si_du : marché ouvert -> abandonné avant tout calcul")


# ── Snapshot déjà fait aujourd'hui -> idempotent ──
_reset(deja_fait=True)
assert history.snapshot_si_du("admin") is False
assert sauvegardes == []
print("✓ snapshot_si_du : déjà fait aujourd'hui -> pas de doublon")


# ── Aucune position -> rien à sauvegarder ──
_reset()
positions_mod.get_positions = lambda u: []
assert history.snapshot_si_du("admin") is False
print("✓ snapshot_si_du : aucune position -> pas de snapshot")


# ── Cas nominal : positions valorisées au prix live ──
_reset()
positions_mod.get_positions = lambda u: [
    {"ticker": "AAA", "type": "achat", "quantite": 10, "prix_achat": 5.0, "currency": "USD"},
    {"ticker": "BBB", "type": "achat", "quantite": 5,  "prix_achat": 20.0, "currency": "USD"},
]
market_mod.get_live_price = lambda t: {"price": {"AAA": 6.0, "BBB": 18.0}[t]}
positions_mod.get_portfolio_summary = lambda u, t, prix: {
    "currency": "USD", "position_fermee": False,
    "valeur_actuelle": prix * {"AAA": 10, "BBB": 5}[t],
    "lots": [], "pnl_euros": 0,
}
assert history.snapshot_si_du("admin") is True
assert len(sauvegardes) == 1
_, saved_positions = sauvegardes[0]
assert len(saved_positions) == 2
print("✓ snapshot_si_du : positions valorisées au prix live, snapshot sauvegardé")


# ── Prix indisponible sur une position OUVERTE -> abandon, pas de faux 0 ──
_reset()
positions_mod.get_positions = lambda u: [
    {"ticker": "CCC", "type": "achat", "quantite": 1, "prix_achat": 10.0, "currency": "USD"},
]
market_mod.get_live_price = lambda t: {"price": None}
positions_mod.get_portfolio_summary = lambda u, t, prix: {
    "currency": "USD", "position_fermee": False, "valeur_actuelle": 0, "lots": [], "pnl_euros": 0,
}
assert history.snapshot_si_du("admin") is False
assert sauvegardes == []
print("✓ snapshot_si_du : prix indisponible sur position ouverte -> abandonné (pas de faux point à 0)")

print("\n✓ Tous les tests test_portfolio_history.py sont OK (hors réseau)")
