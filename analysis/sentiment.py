# analysis/sentiment.py
# Analyse de sentiment sur le DataFrame d'articles.
# Deux moteurs disponibles :
#   - VADER  : rapide, sans GPU, bonne baseline
#   - FinBERT: précis sur les textes financiers, nécessite ~400MB
# Le choix est piloté par config.USE_FINBERT.

import pandas as pd
import numpy  as np
from config import USE_FINBERT, NLP_MODEL


# ── Moteur VADER ──────────────────────────────────────────
def _score_vader(text: str) -> dict:
    """
    Analyse un texte avec VADER SentimentIntensityAnalyzer.
    Retourne un dict avec label et score compound (-1 à +1).
    Appelé via df.apply() — doit être léger et rapide.
    """
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    # Instanciation partagée via attribut de fonction (cache simple)
    if not hasattr(_score_vader, "_analyzer"):
        _score_vader._analyzer = SentimentIntensityAnalyzer()
    vs = _score_vader._analyzer.polarity_scores(str(text))
    compound = vs["compound"]
    if   compound >= 0.05:  label = "positive"
    elif compound <= -0.05: label = "negative"
    else:                   label = "neutral"
    return {"label": label, "score": round(compound, 4)}


# ── Moteur FinBERT ─────────────────────────────────────────
def _score_finbert(text: str) -> dict:
    """
    Analyse un texte avec le modèle FinBERT de ProsusAI.
    Télécharge ~400 MB au premier appel (mis en cache).
    Retourne un dict compatible avec _score_vader.
    """
    from transformers import pipeline
    if not hasattr(_score_finbert, "_pipe"):
        _score_finbert._pipe = pipeline(
            "text-classification",
            model=NLP_MODEL,           # "ProsusAI/finbert"
            tokenizer=NLP_MODEL,
            truncation=True,
            max_length=512,
        )
    result  = _score_finbert._pipe(str(text)[:512])[0]
    label   = result["label"].lower()    # "positive/negative/neutral"
    score_v = result["score"]
    # Convertit en scale [-1, +1] pour homogénéité avec VADER
    compound = score_v if label == "positive" else -score_v if label == "negative" else 0
    return {"label": label, "score": round(compound, 4)}


# ── Analyse principale ────────────────────────────────────
def analyze_sentiment(df_articles: pd.DataFrame) -> dict:
    """
    Applique l'analyse de sentiment sur tout le DataFrame.

    Utilise df.apply() pour vectoriser l'appel au modèle NLP.
    Pandas agrège ensuite les résultats avec .mean() et .value_counts().

    Paramètres
    ----------
    df_articles : DataFrame retourné par get_all_news()
                  doit contenir la colonne 'texte_full'

    Retour
    ------
    dict avec :
      'score'          : float global -1 à +1
      'score_media'    : float 0-100 (pour le moteur de score)
      'label'          : str "positif" / "négatif" / "neutre"
      'df_annote'      : DataFrame avec colonnes sentiment ajoutées
      'repartition'    : pd.Series (nb articles par label)
    """
    if df_articles.empty:
        return {"score": 0, "score_media": 50,
                "label": "neutre", "df_annote": df_articles,
                "repartition": pd.Series(dtype=int)}

    # Sélection du moteur NLP selon la config
    _score_fn = _score_finbert if USE_FINBERT else _score_vader

    # Application vectorisée sur la colonne texte_full
    # .apply() retourne une Series de dicts → pd.json_normalize
    results_raw = df_articles["texte_full"].apply(_score_fn)
    results_df  = pd.json_normalize(results_raw)   # → colonnes label, score

    # Fusion avec le DataFrame principal
    df_out = df_articles.copy()
    df_out["sentiment_label"] = results_df["label"].values
    df_out["sentiment_score"] = results_df["score"].values

    # Agrégation : neutres comptent moins (titres financiers souvent neutres)
    # Les articles sectoriels pèsent 50% moins que les articles entreprise
    label_weights = df_out["sentiment_label"].map({
        "positive": 1.2, "negative": 1.2, "neutral": 0.35,
    }).fillna(0.5)
    type_factor = df_out.get("type", pd.Series("ticker", index=df_out.index)).map(
        {"ticker": 1.0, "secteur": 0.5}
    ).fillna(1.0)
    weights = label_weights * type_factor
    score_global = float(
        np.average(df_out["sentiment_score"], weights=weights)
    )

    repartition = df_out["sentiment_label"].value_counts()

    # score_global ∈ [-1, +1] → score_media ∈ [0, 100]
    score_media = float(np.clip((score_global + 1) * 50, 0, 100))

    # Label global déterminé par la valeur du score moyen
    if   score_global >= 0.05:  label = "positif"
    elif score_global <= -0.05: label = "négatif"
    else:                        label = "neutre"

    return {
        "score":       round(score_global, 3),
        "score_media": round(score_media,  1),
        "label":       label,
        "df_annote":   df_out,       # DataFrame enrichi pour l'UI
        "repartition": repartition,  # pd.Series pour graphiques
    }
