# tests/test_mailer_digest.py — groupage des alertes email par passage.
#
# Aucun email réel : on monkeypatche mailer._envoyer (le point de sortie
# unique ajouté avec le groupage) pour capturer ce qui PARTIRAIT. Toute la
# logique amont (construction des corps, mise en attente, synthèse) est
# ainsi testée sans clé Resend ni réseau.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from alerts import mailer

envois = []   # chaque envoi capturé : (destinataire, sujet, html)
mailer._envoyer = lambda dest, sujet, html, note="": envois.append((dest, sujet, html))


def _alerte_variation(ticker="TMC", variation=-5.2, dest="a@b.c"):
    mailer.send_alert(to_email=dest, username="admin", ticker=ticker,
                      company=ticker + " Inc.", old_reco="ACHETER",
                      new_reco="ACHETER", score=55.0, prix=3.5,
                      variation=variation, var_triggered=True)


# ── Hors groupage : envoi immédiat, comportement historique inchangé ──
envois.clear()
_alerte_variation()
assert len(envois) == 1
assert "TMC" in envois[0][1] and "-5.2" in envois[0][1]
print("✓ hors groupage : une alerte part immédiatement, sujet inchangé")


# ── Groupage, une seule alerte : même email que l'envoi immédiat ──
envois.clear()
mailer.demarrer_groupage()
_alerte_variation()
assert envois == []   # rien ne part pendant le passage
mailer.envoyer_groupes()
assert len(envois) == 1
assert "Variation significative" in envois[0][1]   # sujet individuel conservé
print("✓ groupage, alerte isolée : l'email individuel part tel quel à la fin du passage")


# ── Groupage, plusieurs alertes même destinataire : UNE synthèse ──
envois.clear()
mailer.demarrer_groupage()
_alerte_variation("TMC", -5.2)
mailer.send_advice_change_alert(to_email="a@b.c", username="admin",
                                ticker="FCEL", company="FuelCell",
                                old_action="TENIR", new_action="VENDRE",
                                advice={"raisonnement": "stop loss"}, prix=19.13)
mailer.send_tp_sl_alert(to_email="a@b.c", username="admin", ticker="ITG",
                        company="Intchains", level_type="stop_loss",
                        prix_live=11.0, prix_cible=11.04)
mailer.envoyer_groupes()
assert len(envois) == 1                       # un seul email pour les 3 alertes
dest, sujet, html = envois[0]
assert sujet.startswith("[StockDecisionEngine] 3 alertes")
for t in ("TMC", "FCEL", "ITG"):
    assert t in html                          # les 3 alertes complètes dans le corps
assert "TENIR" in html and "VENDRE" in html   # le détail conseil est conservé
print("✓ groupage : 3 alertes du même passage fusionnées en un email de synthèse")


# ── Groupage, destinataires différents : un email chacun ──
envois.clear()
mailer.demarrer_groupage()
_alerte_variation("TMC", -5.0, dest="un@x.y")
_alerte_variation("FCEL", -10.0, dest="deux@x.y")
mailer.envoyer_groupes()
assert len(envois) == 2
assert {e[0] for e in envois} == {"un@x.y", "deux@x.y"}
print("✓ groupage : les alertes restent séparées par destinataire")


# ── Après le flush : groupage désactivé, retour à l'envoi immédiat ──
envois.clear()
_alerte_variation()
assert len(envois) == 1
mailer.envoyer_groupes()   # tampon vide -> aucun envoi, pas de crash
assert len(envois) == 1
print("✓ après envoyer_groupes : envoi immédiat restauré, flush à vide inoffensif")

# ── send_premarche_digest : sujet reflète le nombre de gaps notables ──
envois.clear()
etats = [
    {"ticker": "AAA", "company": "AAA Inc.", "prix": 5.5, "prev_close": 5.0,
     "gap_pct": 10.0, "confirme": True, "notable": True},
    {"ticker": "BBB", "company": "BBB Corp.", "prix": 20.2, "prev_close": 20.0,
     "gap_pct": 1.0, "confirme": True, "notable": False},
    {"ticker": "CCC", "company": "CCC Ltd.", "prix": None, "prev_close": 9.1,
     "gap_pct": None, "confirme": False, "notable": False},   # pas de prix pré-marché
]
mailer.send_premarche_digest("a@b.c", "admin", etats)
assert len(envois) == 1
dest, sujet, html = envois[0]
assert "1 mouvement(s) notable(s)" in sujet
assert all(t in html for t in ("AAA", "BBB", "CCC"))
assert "⚠" in html               # badge notable présent pour AAA
assert "Pas de donnée" in html   # CCC (gap_pct=None, prix=None) affiché sans rien inventer
print("✓ send_premarche_digest : gap notable distingué, 'Pas de donnée' si pas de prix pré-marché")

print("\n✓ Tous les tests test_mailer_digest.py sont OK (hors réseau)")
