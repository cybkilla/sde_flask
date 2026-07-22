# analysis/divergence.py — écart entre le signal technique et le signal
# structurel (fondamental + média)
#
# Motivé par un cas réel (TMC, semaine du 13-21.07.2026) : des news
# positives (permis d'exploitation obtenu, rachat de parts Allseas)
# datées du 07 au 18.07 ont maintenu un score média élevé (75/100)
# pendant que la composante technique (40% du poids, la plus lourde)
# tirait le score global vers VENDRE. La divergence était réellement
# présente dans les données dès le 07.07 — mais invisible, noyée dans
# la moyenne pondérée, jusqu'à ce que le cours rattrape les fondamentaux
# le 21.07 (+8% en une séance). Cette fonction rend ce signal visible
# SÉPARÉMENT du score agrégé, dès qu'il existe.

from config import SCORE_BUY, SCORE_SELL, WEIGHT_FUND, WEIGHT_MEDIA


def detecter_divergence(score_tech: float, score_fund: float, score_media: float) -> dict | None:
    """
    Fonction PURE. Retourne un dict si le signal technique (court/moyen
    terme, 14-50j) et le signal structurel (fondamental+média reblendés,
    hors technique) pointent dans des directions nettement opposées.
    Retourne None si pas de divergence nette (cas normal, la majorité
    du temps).

    Le signal structurel reblende fondamental et média SANS la
    technique, aux mêmes proportions relatives que la config
    (WEIGHT_FUND/WEIGHT_MEDIA) — c'est la question "que disent le bilan
    et les actualités, indépendamment du momentum court terme ?".

    Deux directions :
      "haussiere_ignoree" : technique baissier (<= SCORE_SELL), mais le
        structurel est haussier (>= SCORE_BUY) — cas TMC : des bonnes
        nouvelles / fondamentaux solides noyés par la technique.
      "baissiere_ignoree" : technique haussier (>= SCORE_BUY), mais le
        structurel est baissier (<= SCORE_SELL) — un momentum court
        terme sans base fondamentale ou médiatique, risque de
        retournement si le momentum s'essouffle.
    """
    poids_total = WEIGHT_FUND + WEIGHT_MEDIA
    if poids_total <= 0:
        return None
    score_structurel = (score_fund * WEIGHT_FUND + score_media * WEIGHT_MEDIA) / poids_total

    if score_tech <= SCORE_SELL and score_structurel >= SCORE_BUY:
        direction = "haussiere_ignoree"
    elif score_tech >= SCORE_BUY and score_structurel <= SCORE_SELL:
        direction = "baissiere_ignoree"
    else:
        return None

    return {
        "direction":         direction,
        "score_tech":        round(float(score_tech), 1),
        "score_structurel":  round(float(score_structurel), 1),
        "ecart":             round(abs(score_structurel - score_tech), 1),
    }
