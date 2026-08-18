# tests/test_portfolio_summary.py — get_portfolio_summary(), hors réseau.
#
# Demandé le 18.08.2026 : pnl_pct (dilué sur TOUT l'historique d'achat,
# ventes passées comprises) sert à la fois d'affichage "performance
# globale" ET, jusqu'ici, de valeur pilotant les seuils de risque
# (stop loss, take profit, renforcement) dans advisor.py — alors que
# ces seuils sont censés protéger la position ACTUELLEMENT détenue,
# pas mesurer la performance de tout l'historique de trading. La
# dilution atténue TOUJOURS le pourcentage vers zéro (quel que soit le
# signe du P&L réalisé), donc retarde le déclenchement des seuils par
# rapport à ce que le % ATR configuré est censé garantir.
#
# get_portfolio_summary() garde pnl_pct (dilué, pour l'affichage) et
# expose maintenant aussi pnl_position_pct (non dilué, coût moyen des
# seules actions encore détenues) — c'est CETTE valeur que
# generate_advice() doit utiliser (vérifié dans test_risk.py).

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from portfolio import positions as pos_mod

# ── Cas réel TMC (18.08.2026), vérifié en conversation avec l'utilisateur :
#    import 10768@4.01, achat 2793@3.825, ventes 2692@4.02 et 2717@3.72,
#    prix live 3.77 → coût moyen 3.97, pnl_pct dilué -4.1%, pnl_position_pct -5.1%
pos_mod.get_positions = lambda username, ticker=None: [
    {"ticker": "TMC", "type": "import", "quantite": 10768, "prix_achat": 4.01},
    {"ticker": "TMC", "type": "vente",  "quantite": 2692,  "prix_achat": 4.02},
    {"ticker": "TMC", "type": "achat",  "quantite": 2793,  "prix_achat": 3.825},
    {"ticker": "TMC", "type": "vente",  "quantite": 2717,  "prix_achat": 3.72},
]

s = pos_mod.get_portfolio_summary("admin", "TMC", 3.77)
assert abs(s["cout_moyen"] - 3.9719) < 0.001
assert abs(s["pnl_pct"] - (-4.1)) < 0.05, f"pnl_pct dilué attendu ~-4.1%, obtenu {s['pnl_pct']}"
assert abs(s["pnl_position_pct"] - (-5.08)) < 0.05, \
    f"pnl_position_pct (non dilué) attendu ~-5.1%, obtenu {s['pnl_position_pct']}"
# La dilution atténue TOUJOURS vers zéro : |dilué| < |non dilué| ici
assert abs(s["pnl_pct"]) < abs(s["pnl_position_pct"])
print(f"✓ get_portfolio_summary : cas réel TMC — pnl_pct dilué {s['pnl_pct']}% "
      f"vs pnl_position_pct non dilué {s['pnl_position_pct']}%, cohérent avec la conversation")


# ── Sans historique de ventes : les deux valeurs sont IDENTIQUES ──
# (la dilution ne fait une différence que s'il y a eu des ventes passées)
pos_mod.get_positions = lambda username, ticker=None: [
    {"ticker": "AAA", "type": "achat", "quantite": 100, "prix_achat": 10.0},
]
s2 = pos_mod.get_portfolio_summary("admin", "AAA", 9.0)
assert s2["pnl_pct"] == s2["pnl_position_pct"] == -10.0
print("✓ get_portfolio_summary : sans vente passée, pnl_pct == pnl_position_pct (pas de dilution)")


# ── Position clôturée (total_shares <= 0) : pnl_position_pct = None ──
# (pas de sens de mesurer le P&L d'actions qu'on ne détient plus)
pos_mod.get_positions = lambda username, ticker=None: [
    {"ticker": "BBB", "type": "achat", "quantite": 100, "prix_achat": 10.0},
    {"ticker": "BBB", "type": "vente", "quantite": 100, "prix_achat": 12.0},
]
s3 = pos_mod.get_portfolio_summary("admin", "BBB", 12.0)
assert s3["position_fermee"] is True
assert s3["pnl_position_pct"] is None
assert s3["pnl_pct"] == 20.0   # le dilué reste pertinent : le trade a rapporté +20%
print("✓ get_portfolio_summary : position clôturée -> pnl_position_pct None, pnl_pct reste informatif")

print("\n✓ Tous les tests test_portfolio_summary.py sont OK (hors réseau)")
