# tests/test_positions_cash.py — correction manuelle admin du cash
# disponible, hors réseau (db monkeypatché, comme test_screener.py).

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db
from portfolio import positions as pos_mod

# ── Lots fictifs : 1000 vendus, 400 achetés -> solde brut suivi = 600 ──
pos_mod.get_positions = lambda username: [
    {"ticker": "AAA", "type": "vente", "quantite": 100, "prix_achat": 10.0},
    {"ticker": "BBB", "type": "achat", "quantite": 40,  "prix_achat": 10.0},
    {"ticker": "CCC", "type": "import", "quantite": 999, "prix_achat": 1.0},  # exclu du calcul
]

assert pos_mod._solde_suivi_brut("admin") == 600.0
print("✓ _solde_suivi_brut : ventes - achats, lots 'import' exclus")


# ── get_ajustement_cash : 0 si Supabase indispo ou aucune ligne ──
db.is_available = lambda: False
assert pos_mod.get_ajustement_cash("admin") == 0.0

db.is_available = lambda: True
db.find_one = lambda table, filt: None
assert pos_mod.get_ajustement_cash("admin") == 0.0
print("✓ get_ajustement_cash : 0 par défaut (Supabase indispo ou aucune correction)")


# ── get_cash_disponible : comportement historique inchangé sans correction ──
db.is_available = lambda: False   # get_ajustement_cash retombe à 0 -> comportement d'avant
assert pos_mod.get_cash_disponible("admin") == 600.0

pos_mod.get_positions = lambda username: [
    {"ticker": "AAA", "type": "achat", "quantite": 100, "prix_achat": 10.0},   # 1000 achetés, rien vendu
]
assert pos_mod.get_cash_disponible("admin") is None   # solde négatif, pas de correction -> None (comportement historique)
print("✓ get_cash_disponible : inchangé sans correction admin (None si négatif)")


# ── corriger_cash : refuse sans Supabase ──
try:
    pos_mod.corriger_cash("admin", 500.0)
    raise AssertionError("aurait dû lever RuntimeError")
except RuntimeError:
    pass
print("✓ corriger_cash : refuse sans Supabase disponible")


# ── corriger_cash calcule l'ÉCART, pas une valeur figée ──
pos_mod.get_positions = lambda username: [
    {"ticker": "AAA", "type": "vente", "quantite": 100, "prix_achat": 10.0},
    {"ticker": "BBB", "type": "achat", "quantite": 40,  "prix_achat": 10.0},
]   # solde brut = 600
db.is_available = lambda: True
sauvegardes = []
db.update_one = lambda table, filt, update, upsert=False: sauvegardes.append((table, filt, update, upsert))

ajustement = pos_mod.corriger_cash("admin", 500.0, note="dépôt externe")
assert ajustement == -100.0    # 500 réel - 600 brut suivi = -100 à corriger
assert len(sauvegardes) == 1
table, filt, update, upsert = sauvegardes[0]
# Stocké sur `users` (pas une table séparée) — attribut scalaire par
# utilisateur, comme email/password. UPDATE simple (upsert=False par
# défaut) : la ligne users existe déjà, un upsert créerait un compte
# fantôme sur une faute de frappe de username.
assert table == "users" and filt == {"username": "admin"} and upsert is False
assert update["$set"]["cash_ajustement"] == -100.0
assert update["$set"]["cash_ajustement_note"] == "dépôt externe"
print("✓ corriger_cash : stocke l'ÉCART sur users (UPDATE, pas upsert)")


# ── get_cash_disponible applique la correction, plancher à 0 ──
db.find_one = lambda table, filt: {"cash_ajustement": -100.0}
assert pos_mod.get_cash_disponible("admin") == 500.0   # 600 + (-100)
print("✓ get_cash_disponible : applique la correction stockée")

db.find_one = lambda table, filt: {"cash_ajustement": -1000.0}   # correction qui rendrait le solde négatif
assert pos_mod.get_cash_disponible("admin") == 0.0   # plancher à 0, jamais négatif avec une correction active
print("✓ get_cash_disponible : plancher à 0 quand une correction rend le solde négatif")

print("\n✓ Tous les tests test_positions_cash.py sont OK (hors réseau)")
