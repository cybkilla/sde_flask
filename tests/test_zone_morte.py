# tests/test_zone_morte.py — explication de la "zone morte" de renforcement.
#
# Cas réel ITG (03.08.2026) : score ACHETER 62-73/100, P&L légèrement
# négatif (-0.6% à -4.6%, coût moyen 13.80$), RSI pas assez bas — aucune
# branche RENFORCER de generate_advice() ne matche (ni repli suffisant,
# ni RSI oversold), donc TENIR par défaut, 4 fois de suite, avec le même
# texte générique qui ne dit jamais pourquoi. Ajoute une ligne explicite.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from portfolio.advisor import generate_advice

_market = {"price": 13.17, "rsi": 55.0}   # RSI 55 > seuil rsi_renforcer (42) -> pas oversold
_summary = {"pnl_pct": -4.6, "total_shares": 100, "cout_moyen": 13.80,
            "lots": [{"type": "achat", "date_achat": "2026-06-01"}]}
_snap = {"score_global": 73.3, "recommandation": "ACHETER",
         "signals_tech": [], "signals_fund": []}

adv = generate_advice(_summary, _market, _snap)
assert adv["action"] == "TENIR"
assert "Signal fort (73/100) mais pas de renforcement" in adv["raisonnement"]
assert "RSI (55) n'est pas encore assez bas" in adv["raisonnement"]
print("✓ zone morte : score fort + RSI pas oversold -> raison explicite dans le raisonnement")


# ── Variante : RSI oversold mais repli pas assez profond (seuil par défaut -5%) ──
_market2 = {"price": 13.17, "rsi": 35.0}   # RSI sous le seuil -> seule la raison P&L doit apparaître
_summary2 = {**_summary, "pnl_pct": -2.5}
adv2 = generate_advice(_summary2, _market2, _snap)
assert adv2["action"] == "TENIR"
assert "repli (-2.5%) n'atteint pas encore le seuil de renforcement" in adv2["raisonnement"]
assert "RSI" not in adv2["raisonnement"].split("mais pas de renforcement")[1].split(".")[0], \
    "le RSI est déjà assez bas ici, il ne doit pas être cité comme blocage"
print("✓ zone morte : seule la raison réellement bloquante (P&L) est citée, pas le RSI déjà bon")


# ── Score faible ou déjà en profit : pas de note ajoutée (comportement inchangé) ──
_snap_faible = {"score_global": 50.0, "recommandation": "NEUTRE",
                "signals_tech": [], "signals_fund": []}
adv3 = generate_advice(_summary, _market, _snap_faible)
assert "pas de renforcement" not in adv3["raisonnement"]

_summary_profit = {**_summary, "pnl_pct": 3.0}
adv4 = generate_advice(_summary_profit, _market, _snap)
assert "pas de renforcement" not in adv4["raisonnement"]
print("✓ zone morte : aucune note quand le score est faible ou la position déjà en profit")

print("\n✓ Tous les tests test_zone_morte.py sont OK (hors réseau)")
