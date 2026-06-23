# analysis/media_score.py
# Calcule le score médiatique final en combinant :
#   - sentiment NLP des articles (VADER / FinBERT)
#   - signal insider (achats vs ventes)
#   - pénalités événements dirigeants
# Retourne un dict compatible avec le pipeline.

import numpy  as np
import pandas as pd


def compute_media_score(
    sentiment: dict,
    insider_score: dict,
    df_events: pd.DataFrame,
) -> dict:
    """
    Agrège les trois sources médiatiques en un score 0-100.

    Composition :
      60% sentiment articles       (NLP)
      25% signal insider           (achats / ventes)
      15% pénalité événements CEO  (fraud, divorce…)

    Paramètres
    ----------
    sentiment     : dict retourné par analyze_sentiment()
    insider_score : dict retourné par get_insider_score()
    df_events     : DataFrame retourné par get_executive_events()
    """
    # ── Composante 1 : sentiment NLP (60%) ────────────────
    # score_media est déjà normalisé 0-100 par analyze_sentiment()
    s_sent = sentiment["score_media"] * 0.60

    # ── Composante 2 : signal insider (25%) ───────────────
    # BUY → 100 pts, SELL → 0 pts, NEUTRE → 50 pts
    ins_map = {"BUY": 100, "SELL": 0, "NEUTRE": 50}
    s_ins   = ins_map.get(insider_score["net_signal"], 50) * 0.25

    # ── Composante 3 : pénalité événements (15%) ──────────
    from data.insider import compute_exec_penalty
    total_penalty = compute_exec_penalty(df_events)
    # Pénalité max ~15 pts → impact médiatique max ~2.25 sur 100
    s_pen = total_penalty * 0.15

    # ── Score final ───────────────────────────────────────
    # Base neutre = 50 × 0.15 = 7.5 (quand pas d'événements)
    score_final = float(np.clip(s_sent + s_ins + (7.5 - s_pen), 0, 100))

    # DataFrame Pandas de décomposition (pour l'UI)
    df_detail = pd.DataFrame([
        {"source": "Sentiment NLP",   "contribution": round(s_sent, 1), "poids": "60%"},
        {"source": "Signal insider",  "contribution": round(s_ins,  1), "poids": "25%"},
        {"source": "Pénalité CEO",    "contribution": round(-s_pen, 1), "poids": "15%"},
    ])

    return {
        "score":    round(score_final, 1),
        "detail":   df_detail,
        "alertes":  len(df_events),
    }
