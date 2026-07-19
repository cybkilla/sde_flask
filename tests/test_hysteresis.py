# tests/test_hysteresis.py — lissage de la recommandation, hors réseau.
#
# appliquer_hysteresis() est une fonction PURE : (score, état) -> (reco, état).
# Scénario réel qui a motivé cette règle : le score de TMC a fait
# 43 → 47 → 52 → 57 → 40 → 40 → 42 en une semaine (seuils ACHETER=54,
# VENDRE=46), franchissant les seuils 6 fois.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from analysis.hysteresis import appliquer_hysteresis, MARGE_FRANCHISSEMENT, STREAK_REQUIS
from analysis.scoring import SCORE_BUY, SCORE_SELL


# ── Premier calcul (pas d'état précédent) : adopte la reco brute telle quelle ──
reco, etat = appliquer_hysteresis(43.0, None)
assert reco == "VENDRE"
assert etat == {"hyst_stable": "VENDRE", "hyst_candidat": None, "hyst_streak": 0}
print("✓ premier calcul : reco brute adoptée directement, pas d'hystérésis à faire")


# ── Statu quo : la reco brute confirme la stable → rien ne change ──
reco2, etat2 = appliquer_hysteresis(44.0, etat)   # toujours VENDRE (44 < 46)
assert reco2 == "VENDRE"
assert etat2["hyst_candidat"] is None and etat2["hyst_streak"] == 0
print("✓ statu quo : la reco stable est confirmée, aucun candidat en attente")


# ── Petit franchissement (score juste au-dessus du seuil NEUTRE) : ──
# le candidat NEUTRE doit attendre STREAK_REQUIS confirmations avant de
# devenir stable — c'est exactement le cas TMC (43→47, un point sous le
# seuil de marge) qui n'aurait pas dû faire flipper la reco tout de suite.
reco3, etat3 = appliquer_hysteresis(47.0, etat2)   # NEUTRE (46 <= 47 <= 54), 1er jour
assert reco3 == "VENDRE", "la reco stable ne doit PAS flipper au 1er jour du candidat"
assert etat3["hyst_candidat"] == "NEUTRE" and etat3["hyst_streak"] == 1

reco4, etat4 = appliquer_hysteresis(52.0, etat3)   # NEUTRE confirmé un 2e jour
assert reco4 == "NEUTRE", "2e confirmation consécutive → la reco stable adopte NEUTRE"
assert etat4["hyst_candidat"] is None and etat4["hyst_streak"] == 0
print(f"✓ confirmation sur {STREAK_REQUIS} calculs frais : la reco stable finit par suivre")


# ── Franchissement DÉCISIF (marge dépassée) : flip immédiat, pas d'attente ──
reco5, etat5 = appliquer_hysteresis(SCORE_BUY + MARGE_FRANCHISSEMENT + 1, etat4)
assert reco5 == "ACHETER", "un score net au-dessus du seuil+marge doit flipper tout de suite"
assert etat5["hyst_candidat"] is None and etat5["hyst_streak"] == 0
print("✓ franchissement net (score au-delà de la marge) : flip immédiat sans attendre")


# ── Le candidat change en cours de route : le streak repart de 1, pas de mélange ──
_, e = appliquer_hysteresis(50.0, None)                  # stable = NEUTRE (46<50<54)
assert e["hyst_stable"] == "NEUTRE"
# 56 : ACHETER mais SOUS la marge de franchissement (54+5=59) → candidat, pas flip
r, e = appliquer_hysteresis(56.0, e)   # candidat ACHETER, jour 1
assert r == "NEUTRE" and e["hyst_candidat"] == "ACHETER" and e["hyst_streak"] == 1
r, e = appliquer_hysteresis(44.0, e)   # candidat change → VENDRE (sous la marge), repart à 1
assert r == "NEUTRE", "un changement de candidat ne doit pas hériter du streak précédent"
assert e["hyst_candidat"] == "VENDRE" and e["hyst_streak"] == 1
print("✓ changement de candidat en cours de route : le streak repart de zéro, pas de mélange")


# ── Rejoue les scores RÉELS de TMC (08 au 19.07.2026, table daily_advice) ──
# combien de fois la reco AURAIT changé sans hystérésis vs avec ?
from analysis.scoring import recommandation
scores_semaine = [43.2, 42.6, 46.0, 46.5, 46.7, 47.2, 52.5, 57.3, 39.9, 39.9, 41.8]

brutes = [recommandation(s) for s in scores_semaine]
changements_bruts = sum(1 for i in range(1, len(brutes)) if brutes[i] != brutes[i-1])

etat_e = None
stables = []
for s in scores_semaine:
    r, etat_e = appliquer_hysteresis(s, etat_e)
    stables.append(r)
changements_stables = sum(1 for i in range(1, len(stables)) if stables[i] != stables[i-1])

assert changements_bruts == 3, f"attendu 3 changements bruts sur la semaine réelle, obtenu {changements_bruts}"
assert changements_stables < changements_bruts, \
    "l'hystérésis doit réduire le nombre de changements de reco sur ce cas réel"
# Le cas concret le plus parlant : le score du 16.07 (57.3, ACHETER) n'a
# duré qu'UN jour avant de retomber à 39.9 (VENDRE) le lendemain — jamais
# confirmé. Avec hystérésis, ce blip d'un jour ne devient JAMAIS la reco
# stable (elle reste NEUTRE, l'ancien état, plutôt que de flipper vers
# ACHETER puis revenir à VENDRE le jour suivant).
assert "ACHETER" not in stables, \
    "le blip ACHETER d'un seul jour (score 57.3) ne doit jamais devenir stable"
print(f"✓ semaine TMC réelle rejouée : {changements_bruts} changements bruts → {changements_stables} "
      f"avec hystérésis — le blip ACHETER d'un jour (57.3) est filtré")
print(f"  brutes  : {brutes}")
print(f"  stables : {stables}")

print("\n✓ Tous les tests test_hysteresis.py sont OK (hors réseau)")
