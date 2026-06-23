# analysis/prompt_builder.py
# Construit le prompt envoyé au LLM à partir du dict résultat.
# Utilise Pandas pour extraire les signaux actifs proprement.
# Le prompt est court (<300 tokens) pour rester dans les limites
# du tier gratuit Groq.

import pandas as pd
from analysis.explainer import build_explanation_df


def build_prompt(result: dict) -> str:
    """
    Construit un prompt structuré et concis pour le LLM.

    Stratégie :
      - Fournir uniquement les données nécessaires à l'explication
      - Garder le prompt < 400 tokens pour rester gratuit
      - Utiliser Pandas pour trier et filtrer les signaux avant
        de les injecter dans le texte

    Paramètres
    ----------
    result : dict retourné par pipeline.run()

    Retour
    ------
    str : prompt prêt à envoyer au LLM
    """
    ticker = result["ticker"]
    name   = result["company_name"]
    reco   = result["recommandation"]
    score  = result["score_global"]
    tech   = result["score_tech"]
    fund   = result["score_fund"]
    media  = result["score_media"]
    sent   = result["sentiment"]["label"]
    ceo    = result["ceo_name"]
    prix   = result["market"]["price"]
    rsi    = result["market"]["rsi"]

    # ── Extraction des signaux clés via Pandas ────────────
    # On utilise build_explanation_df() pour avoir un DataFrame
    # trié par impact, puis on filtre les 4 plus importants
    df_exp = build_explanation_df(result)

    # Top 4 signaux haussiers
    top_bull = (
        df_exp[df_exp["sens"] == "haussier"]
        .head(4)["signal"]
        .tolist()
    )

    # Top 3 signaux baissiers
    top_bear = (
        df_exp[df_exp["sens"] == "baissier"]
        .head(3)["signal"]
        .tolist()
    )

    # Alertes CEO si présentes (Pandas DataFrame)
    df_ev     = result.get("df_events", pd.DataFrame())
    nb_alerts = len(df_ev)
    alert_str = ""
    if nb_alerts > 0 and "mot_cle" in df_ev.columns:
        # Extrait les mots-clés détectés pour le prompt
        kws = df_ev["mot_cle"].unique().tolist()[:3]
        alert_str = f"\nAlertes CEO détectées : {', '.join(kws)}."

    # ── Assemblage du prompt ──────────────────────────────
    # Format structuré pour guider le LLM vers une explication précise
    prompt = f"""Données d'analyse boursière :

Société       : {name} ({ticker})
CEO           : {ceo}
Prix actuel   : ${prix:.2f}
RSI 14j       : {rsi:.1f}

Score global  : {score}/100  →  Recommandation : {reco}
  - Score technique   : {tech}/100
  - Score fondamental : {fund}/100
  - Score médiatique  : {media}/100
  - Sentiment actualités : {sent}
{alert_str}

Signaux haussiers actifs :
{chr(10).join(f"  + {s}" for s in top_bull) or "  (aucun)"}

Signaux baissiers actifs :
{chr(10).join(f"  - {s}" for s in top_bear) or "  (aucun)"}

En 3 phrases maximum, explique pourquoi ce score de {score}/100 \
a été attribué et ce que cela signifie pour un investisseur."""

    return prompt
