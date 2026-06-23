# analysis/explainer.py
# Génère un DataFrame Pandas d'explication complet
# pour l'affichage dans l'interface Streamlit.
# Objectif : rendre le score transparent et pédagogique.

import pandas as pd
import numpy  as np


def build_explanation_df(result: dict) -> pd.DataFrame:
    """
    Construit un DataFrame récapitulatif de tous les signaux actifs.

    Format de sortie (un signal par ligne) :
      categorie | signal | points | sens | icone

    Utilisé par st.dataframe() dans l'interface Streamlit
    pour afficher "pourquoi cette recommandation".
    """
    rows = []

    # ── Signaux techniques ────────────────────────────────
    for sig in result.get("signals_tech", []):
        rows.append({
            "catégorie": "Technique",
            "signal":    sig["nom"],
            "points":    sig["points"],
            "sens":      sig["sens"],
            "icone":     "↑" if sig["sens"] == "haussier" else "↓",
        })

    # ── Signaux fondamentaux ──────────────────────────────
    for sig in result.get("signals_fund", []):
        rows.append({
            "catégorie": "Fondamental",
            "signal":    sig["nom"],
            "points":    sig["points"],
            "sens":      sig["sens"],
            "icone":     "↑" if sig["sens"] == "haussier" else "↓",
        })

    # ── Signal insider (ligne unique) ─────────────────────
    ins = result.get("insider_score", {})
    ins_sig = ins.get("net_signal", "NEUTRE")
    ins_pts = 12 if ins_sig == "BUY" else (-12 if ins_sig == "SELL" else 0)
    if ins_sig != "NEUTRE" or ins.get("achats") or ins.get("ventes"):
        rows.append({
            "catégorie": "Médiatique",
            "signal":    (
                f"Insiders : {ins.get('achats', 0):,} titres achetés / "
                f"{ins.get('ventes', 0):,} vendus ({ins_sig})"
            ),
            "points":    ins_pts,
            "sens":      "haussier" if ins_pts > 0 else ("baissier" if ins_pts < 0 else "neutre"),
            "icone":     "↑" if ins_pts > 0 else ("↓" if ins_pts < 0 else "◆"),
        })

    # ── Alertes dirigeants ────────────────────────────────
    df_ev = result.get("df_events", pd.DataFrame())
    if not df_ev.empty:
        seen_urls = set()
        for _, row in df_ev.iterrows():
            url = row.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            pts = -int(row.get("penalite", 5))
            rows.append({
                "catégorie": "Médiatique",
                "signal":    f"Alerte CEO ({row['mot_cle']}) — {row['severite']}",
                "points":    pts,
                "sens":      "baissier",
                "icone":     "⚠",
            })

    # Construit le DataFrame et trie par impact décroissant
    df = (
        pd.DataFrame(rows)
        .sort_values("points", ascending=False, key=abs)
        .reset_index(drop=True)
    )

    # Colonne "impact" visuelle pour st.dataframe()
    # np.where vectorisé remplace un .apply(lambda)
    df["impact"] = np.where(df["points"] > 0,
        df["points"].astype(str).radd("+"),
        df["points"].astype(str)
    )

    return df[["catégorie","icone","signal","impact","sens"]]
