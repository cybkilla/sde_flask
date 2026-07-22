# tests/test_divergence.py — écart technique vs structurel, hors réseau.
#
# detecter_divergence() est une fonction PURE : testable avec de simples
# nombres, sans marché ni base de données.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from analysis.divergence import detecter_divergence
from config import SCORE_BUY, SCORE_SELL


# ── Cas TMC réel (approximatif) : technique baissier, structurel haussier ──
# News positives (permis d'exploitation, rachat de parts) + fondamentaux
# corrects, noyés par une technique bearish — le rebond du 21.07 a
# confirmé après coup ce que la divergence aurait signalé dès le 07.07.
d = detecter_divergence(score_tech=30.0, score_fund=55.0, score_media=75.0)
assert d is not None
assert d["direction"] == "haussiere_ignoree"
assert d["score_tech"] == 30.0
# structurel = (55*0.35 + 75*0.25) / 0.60 = 63.33
assert abs(d["score_structurel"] - 63.33) < 0.1
assert d["ecart"] > 30
print(f"✓ divergence haussière ignorée (cas TMC) : technique {d['score_tech']}, "
      f"structurel {d['score_structurel']}, écart {d['ecart']}")

# ── Symétrique : technique haussier, structurel baissier ──
# Momentum court terme sans base fondamentale/médiatique
d2 = detecter_divergence(score_tech=65.0, score_fund=35.0, score_media=30.0)
assert d2 is not None
assert d2["direction"] == "baissiere_ignoree"
print(f"✓ divergence baissière ignorée : technique {d2['score_tech']}, "
      f"structurel {d2['score_structurel']}")

# ── Pas de divergence : les trois scores alignés ──
assert detecter_divergence(50.0, 50.0, 50.0) is None
assert detecter_divergence(60.0, 58.0, 62.0) is None   # tous haussiers, cohérent
assert detecter_divergence(35.0, 32.0, 38.0) is None   # tous baissiers, cohérent
print("✓ scores alignés → aucune divergence signalée")

# ── Cas limites : un seul côté franchit le seuil, pas l'autre ──
# Technique baissier mais structurel seulement neutre (pas franchement
# haussier) → pas de divergence, pas de fausse alerte
assert detecter_divergence(30.0, 50.0, 50.0) is None
# Structurel haussier mais technique seulement neutre → idem
assert detecter_divergence(50.0, 65.0, 65.0) is None
print("✓ un seul côté franchit le seuil → pas de fausse alerte")

# ── Exactement aux seuils (bornes inclusives) ──
d3 = detecter_divergence(SCORE_SELL, SCORE_BUY, SCORE_BUY)
assert d3 is not None and d3["direction"] == "haussiere_ignoree"
print(f"✓ bornes exactes (SCORE_SELL={SCORE_SELL}, SCORE_BUY={SCORE_BUY}) déclenchent bien")

print("\n✓ Tous les tests test_divergence.py sont OK (hors réseau)")
