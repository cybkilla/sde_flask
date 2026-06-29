# analysis/explainer.py
# Génère un DataFrame Pandas d'explication complet
# pour l'affichage dans l'interface Streamlit.
# Objectif : rendre le score transparent et pédagogique.

import pandas as pd
import numpy  as np
from email.utils import parsedate_to_datetime


def _fmt_rss_date(raw: str) -> str:
    """Convertit une date RSS (RFC 2822) en YYYY-MM-DD, ou retourne '—'."""
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except Exception:
        return str(raw)[:10] if raw else "—"


def build_explanation_df(result: dict) -> pd.DataFrame:
    """
    Construit un DataFrame récapitulatif de tous les signaux actifs.

    Format de sortie (un signal par ligne) :
      categorie | icone | date | signal | impact | sens

    Utilisé par st.dataframe() dans l'interface Streamlit
    pour afficher "pourquoi cette recommandation".
    """
    rows = []

    # Date de la dernière bougie disponible (pour signaux techniques)
    hist = result.get("market", {}).get("history")
    if hist is not None and not hist.empty:
        last_date = pd.Timestamp(hist.index[-1]).strftime("%Y-%m-%d")
    else:
        last_date = "—"

    # ── Signaux techniques ────────────────────────────────
    for sig in result.get("signals_tech", []):
        rows.append({
            "catégorie": "Technique",
            "icone":     "↑" if sig["sens"] == "haussier" else "↓",
            "date":      last_date,
            "signal":    sig["nom"],
            "points":    sig["points"],
            "sens":      sig["sens"],
        })

    # ── Signaux fondamentaux ──────────────────────────────
    for sig in result.get("signals_fund", []):
        rows.append({
            "catégorie": "Fondamental",
            "icone":     "↑" if sig["sens"] == "haussier" else "↓",
            "date":      "—",
            "signal":    sig["nom"],
            "points":    sig["points"],
            "sens":      sig["sens"],
        })

    # ── Signal insider (ligne unique) ─────────────────────
    ins = result.get("insider_score", {})
    ins_sig = ins.get("net_signal", "NEUTRE")
    ins_pts = 12 if ins_sig == "BUY" else (-12 if ins_sig == "SELL" else 0)
    if ins_sig != "NEUTRE" or ins.get("achats") or ins.get("ventes"):
        rows.append({
            "catégorie": "Médiatique",
            "icone":     "↑" if ins_pts > 0 else ("↓" if ins_pts < 0 else "◆"),
            "date":      "—",
            "signal":    (
                f"Insiders : {ins.get('achats', 0):,} titres achetés / "
                f"{ins.get('ventes', 0):,} vendus ({ins_sig})"
            ),
            "points":    ins_pts,
            "sens":      "haussier" if ins_pts > 0 else ("baissier" if ins_pts < 0 else "neutre"),
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
                "icone":     "⚠",
                "date":      _fmt_rss_date(row.get("date", "")),
                "signal":    f"Alerte CEO ({row['mot_cle']}) — {row['severite']}",
                "points":    pts,
                "sens":      "baissier",
            })

    # Construit le DataFrame et trie par impact décroissant
    df = (
        pd.DataFrame(rows)
        .sort_values("points", ascending=False, key=abs)
        .reset_index(drop=True)
    )

    # Colonne "impact" visuelle
    df["impact"] = np.where(df["points"] > 0,
        df["points"].astype(str).radd("+"),
        df["points"].astype(str)
    )

    return df[["catégorie", "icone", "date", "signal", "impact", "sens"]]
