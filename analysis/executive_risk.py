# analysis/executive_risk.py
# Executive Risk Score (0-100) :
#   0  = aucun risque détecté (dirigeants sains)
#   100 = risque maximal (fraude, départ, ventes massives…)
#
# Composition :
#   50% pénalité événements RSS  (scandales / départs / fraudes)
#   30% signal insider           (achats vs ventes nettes)
#   20% concentration            (nb alertes critiques)

import numpy  as np
import pandas as pd
from config import SEVERITY_PENALTY_POINTS


_INS_RISK = {"SELL": 70, "NEUTRE": 35, "BUY": 0}

_LEVEL_THRESHOLDS = [
    (70, "CRITIQUE"),
    (45, "ÉLEVÉ"),
    (20, "MODÉRÉ"),
    (0,  "FAIBLE"),
]


def compute_executive_risk_score(
    df_events:    pd.DataFrame,
    insider_score: dict,
) -> dict:
    """
    Agrège les signaux dirigeants en un score de risque 0-100.

    Paramètres
    ----------
    df_events     : DataFrame retourné par get_executive_events()
    insider_score : dict retourné par get_insider_score()

    Retour
    ------
    dict {
        'score':    float  0-100
        'level':    str    FAIBLE / MODÉRÉ / ÉLEVÉ / CRITIQUE
        'alertes':  int    nombre total d'alertes
        'critique': int    alertes sévérité CRITIQUE
        'detail':   pd.DataFrame  décomposition par composante
        'flags':    list[str]     messages d'alerte lisibles
    }
    """
    flags: list[str] = []

    # ── Composante 1 : pénalité événements RSS (50%) ─────
    penalty_raw = 0.0
    n_critique  = 0
    n_alertes   = 0

    if not df_events.empty:
        # Déduplique par URL pour éviter de compter plusieurs fois le même article
        df_uniq = (
            df_events.drop_duplicates(subset=["url"])
            if "url" in df_events.columns
            else df_events.copy()
        )
        n_alertes = len(df_uniq)

        by_sev = df_uniq.groupby("severite", sort=False)

        for sev, pts in SEVERITY_PENALTY_POINTS.items():
            if pts == 0 or sev not in by_sev.groups:
                continue
            grp = by_sev.get_group(sev)
            penalty_raw += len(grp) * pts
            if sev == "CRITIQUE":
                n_critique = len(grp)
                for _, row in grp.iterrows():
                    flags.append(
                        f"[CRITIQUE] {row.get('mot_cle','?')} — "
                        f"{str(row.get('titre',''))[:90]}"
                    )
            elif sev == "HAUTE":
                for _, row in grp.iterrows():
                    flags.append(
                        f"[HAUTE] {row.get('mot_cle','?')} — "
                        f"{str(row.get('titre',''))[:90]}"
                    )

    # Plafonne la pénalité brute à 100 pts puis applique le poids
    risk_events = float(np.clip(penalty_raw, 0, 100))
    s_events    = risk_events * 0.50

    # ── Composante 2 : signal insider (30%) ─────────────
    ins_signal = insider_score.get("net_signal", "NEUTRE")
    ins_risk   = _INS_RISK.get(ins_signal, 35)
    s_insider  = ins_risk * 0.30

    if ins_signal == "SELL":
        flags.append("[INSIDER] Ventes nettes détectées — pression baissière")

    # ── Composante 3 : concentration risque (20%) ────────
    # Chaque alerte critique = +15 pts, autres = +3 pts
    conc_raw = n_critique * 15 + (n_alertes - n_critique) * 3
    s_conc   = float(np.clip(conc_raw, 0, 100)) * 0.20

    # ── Score final ───────────────────────────────────────
    risk_total = float(np.clip(s_events + s_insider + s_conc, 0, 100))

    level = next(lv for thresh, lv in _LEVEL_THRESHOLDS if risk_total >= thresh)

    df_detail = pd.DataFrame([
        {
            "composante": "Événements RSS",
            "risque_brut": round(risk_events, 1),
            "contribution": round(s_events, 1),
            "poids": "50%",
        },
        {
            "composante": "Signal insider",
            "risque_brut": float(ins_risk),
            "contribution": round(s_insider, 1),
            "poids": "30%",
        },
        {
            "composante": "Concentration risque",
            "risque_brut": round(float(np.clip(conc_raw, 0, 100)), 1),
            "contribution": round(s_conc, 1),
            "poids": "20%",
        },
    ])

    return {
        "score":    round(risk_total, 1),
        "level":    level,
        "alertes":  n_alertes,
        "critique": n_critique,
        "detail":   df_detail,
        "flags":    flags,
    }
