# analysis/hysteresis.py — lisse les allers-retours de la recommandation
#
# Constat de la semaine du 13-19.07 sur TMC : le score global est passé
# 43 → 47 → 52 → 57 → 40 → 40 → 42 en quelques jours, franchissant les
# seuils ACHETER/VENDRE (54/46) SIX fois. Chaque franchissement change
# la recommandation affichée, déclenche potentiellement une escalade de
# conseil (VENDRE fort) et un email — sur un score qui n'a fait que
# respirer autour de sa bande neutre.
#
# Principe : la recommandation BRUTE (recommandation(score) — seuils
# fixes) sert toujours de référence, mais elle n'est adoptée comme
# recommandation STABLE (affichée, utilisée par l'advisor) que si :
#   - elle dépasse le seuil avec une MARGE décisive (mouvement net), OU
#   - elle se confirme sur STREAK_REQUIS calculs FRAIS consécutifs
#     (pas de cache hit — un calcul frais ≈ une fois par jour grâce au
#     TTL 24h du snapshot, donc "consécutifs" ≈ jours consécutifs)
# Sinon, l'ancienne recommandation stable est conservée un peu plus
# longtemps, et la recommandation brute reste visible séparément
# (jamais masquée — la transparence prime sur le lissage).

MARGE_FRANCHISSEMENT = 5   # points au-delà du seuil → flip immédiat, pas d'attente
STREAK_REQUIS         = 2  # calculs frais consécutifs du même candidat pour confirmer


def appliquer_hysteresis(score: float, etat_precedent: dict = None) -> tuple:
    """
    Fonction PURE. Retourne (reco_stable, nouvel_etat).

    etat_precedent : dict {"hyst_stable": str, "hyst_candidat": str|None,
                            "hyst_streak": int} — None au premier calcul.
    """
    from analysis.scoring import SCORE_BUY, SCORE_SELL

    if score > SCORE_BUY:
        brute = "ACHETER"
    elif score < SCORE_SELL:
        brute = "VENDRE"
    else:
        brute = "NEUTRE"

    etat   = dict(etat_precedent) if etat_precedent else {}
    stable = etat.get("hyst_stable") or brute   # premier calcul : pas d'hystérésis à faire

    def _etat(s, cand, streak):
        return {"hyst_stable": s, "hyst_candidat": cand, "hyst_streak": streak}

    if brute == stable:
        # Statu quo confirmé — on efface tout candidat concurrent en cours
        return brute, _etat(stable, None, 0)

    # Franchissement décisif : le score est allé bien au-delà du seuil,
    # pas la peine d'attendre une confirmation — le signal est net.
    franchi_fort = (
        (brute == "ACHETER" and score > SCORE_BUY + MARGE_FRANCHISSEMENT) or
        (brute == "VENDRE"  and score < SCORE_SELL - MARGE_FRANCHISSEMENT)
    )
    if franchi_fort:
        return brute, _etat(brute, None, 0)

    # Sinon : on accumule un streak pour CE candidat précis. S'il change
    # de candidat en cours de route (ex. VENDRE puis NEUTRE avant confirmation
    # de VENDRE), le compteur repart de 1 — pas de mélange entre candidats.
    if etat.get("hyst_candidat") == brute:
        streak = int(etat.get("hyst_streak") or 0) + 1
    else:
        streak = 1

    if streak >= STREAK_REQUIS:
        return brute, _etat(brute, None, 0)
    return stable, _etat(stable, brute, streak)
