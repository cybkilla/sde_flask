# analysis/predictor.py — classifieur probabiliste P(hausse à 20 jours)
#
# L'idée : score_technique() est déjà une somme pondérée de signaux binaires
# — c'est exactement la structure d'une RÉGRESSION LOGISTIQUE, sauf que ses
# poids (+15, -20…) ont été fixés à la main. Ici, on APPREND ces poids des
# données : l'algorithme trouve la combinaison qui colle le mieux à ce qui
# s'est réellement passé sur 2 ans. La sortie n'est pas un prix prédit
# (illusoire) mais une probabilité : "64% de chances que le cours soit plus
# haut dans 20 jours" — une sortie qui dit elle-même son incertitude.
#
# Les features viennent du rejeu du backtest (colonne "signaux" de
# _replay_scores) : le dataset existe déjà, aucune donnée nouvelle.
#
# Discipline de validation (les 3 pièges des séries temporelles) :
#   1. Walk-forward : on entraîne sur le début de la période et on teste
#      sur la FIN — jamais de mélange aléatoire passé/futur.
#   2. Régularisation L2 (paramètre C) : pénalise les poids extrêmes appris
#      sur peu d'épisodes — même rôle que le shrinkage en calibration.
#   3. Taux de base affiché : en marché haussier, "hausse" est vrai ~60%
#      du temps au hasard — le modèle n'a de valeur QUE s'il fait mieux.

import numpy as np
import pandas as pd

from analysis.scoring import TECH_WEIGHTS, TECH_LABELS

HORIZON_DEFAUT = 20     # jours de bourse — aligné sur l'attribution
TEST_FRACTION  = 0.30   # 30% finaux de l'historique réservés au test
MIN_JOURS      = 150    # en dessous : trop peu pour entraîner + tester


def build_dataset(bt: pd.DataFrame, horizon: int = HORIZON_DEFAUT):
    """
    Transforme le rejeu du backtest en dataset de classification.

    X : une colonne 0/1 par signal technique (les 15 codes de TECH_WEIGHTS)
        — chaque ligne est "la photo des signaux" d'un jour de bourse.
    y : True si le cours a monté dans les `horizon` jours suivants.

    Les `horizon` derniers jours n'ont pas de futur observable
    (shift(-h) → NaN) : on les exclut de l'entraînement, mais la DERNIÈRE
    ligne de X servira à prédire "aujourd'hui".
    """
    X = pd.DataFrame(
        {code: bt["signaux"].apply(lambda s: code in s).astype(int)
         for code in TECH_WEIGHTS.index},
        index=bt.index,
    )
    fwd = bt["close"].shift(-horizon) / bt["close"] - 1
    y   = (fwd > 0)

    observable = fwd.notna()
    return X[observable], y[observable], X.iloc[[-1]]


def run_predictor(bt: pd.DataFrame, horizon: int = HORIZON_DEFAUT):
    """
    Entraîne, valide en walk-forward, puis prédit la probabilité du jour.
    Retourne un dict prêt pour le JSON, ou None si sklearn est absent ou
    l'historique trop court — l'appelant continue sans prédiction.
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
    except ImportError:
        print("[Predictor] scikit-learn absent — prédiction désactivée", flush=True)
        return None

    X, y, X_jour = build_dataset(bt, horizon)
    if len(X) < MIN_JOURS:
        return None

    # ── Découpe chronologique (walk-forward) ──────────────────────────
    # iloc[:coupure] = passé (train), iloc[coupure:] = futur (test).
    # SURTOUT PAS train_test_split(shuffle=True) : mélanger les dates
    # ferait "apprendre 2025 pour prédire 2024" — triche invisible.
    coupure = int(len(X) * (1 - TEST_FRACTION))
    X_train, X_test = X.iloc[:coupure], X.iloc[coupure:]
    y_train, y_test = y.iloc[:coupure], y.iloc[coupure:]

    # Il faut les 2 classes dans le train (un titre qui n'a fait que
    # monter ne peut pas apprendre à reconnaître une baisse)
    if y_train.nunique() < 2:
        return None

    # C=0.5 : régularisation L2 un peu plus forte que le défaut (C=1) —
    # nos features sont corrélées entre elles (rsi_bas et macd_bull
    # s'activent souvent ensemble) et les épisodes sont peu nombreux.
    modele = LogisticRegression(C=0.5, max_iter=1000)
    modele.fit(X_train, y_train)

    # ── Métriques honnêtes sur la période jamais vue ──────────────────
    proba_test = modele.predict_proba(X_test)[:, 1]
    acc_test   = float(((proba_test > 0.5) == y_test).mean())
    base_rate  = float(y_test.mean())        # % de hausses "au hasard"
    # AUC : probabilité que le modèle classe un jour de hausse au-dessus
    # d'un jour de baisse — 0.5 = hasard pur, insensible au déséquilibre
    try:
        auc = float(roc_auc_score(y_test, proba_test)) if y_test.nunique() == 2 else None
    except Exception:
        auc = None

    # ── Modèle final : ré-entraîné sur TOUT l'historique ──────────────
    # La validation a mesuré la méthode ; pour prédire aujourd'hui,
    # on ne gaspille pas 30% des données (pratique standard).
    modele_final = LogisticRegression(C=0.5, max_iter=1000)
    modele_final.fit(X, y)
    proba_jour = float(modele_final.predict_proba(X_jour)[0, 1])

    # Coefficients appris, mis face aux poids manuels — la version
    # "apprise" du tableau d'attribution
    coefs = sorted(
        [{"code":  code,
          "label": TECH_LABELS.get(code, code),
          "coef":  round(float(c), 3),
          "poids_manuel": int(TECH_WEIGHTS[code])}
         for code, c in zip(X.columns, modele_final.coef_[0])],
        key=lambda d: d["coef"], reverse=True,
    )

    return {
        "horizon":      horizon,
        "proba_hausse": round(proba_jour * 100, 1),
        "base_rate":    round(base_rate * 100, 1),
        "acc_test":     round(acc_test * 100, 1),
        "auc":          round(auc, 3) if auc is not None else None,
        "n_train":      len(X_train),
        "n_test":       len(X_test),
        # Le modèle bat-il le "toujours hausse" naïf sur la période test ?
        "bat_le_hasard": acc_test > max(base_rate, 1 - base_rate),
        "coefficients": coefs,
    }
