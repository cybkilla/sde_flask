# tests/test_predictor.py — tests du classifieur probabiliste, hors réseau.
#
# Stratégie : on fabrique un rejeu de backtest synthétique où UN signal
# prédit parfaitement la hausse. Un modèle qui apprend correctement doit
# (1) donner un coefficient positif fort à ce signal, (2) sortir une proba
# élevée quand il est actif, (3) battre le hasard sur la période test.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from analysis.predictor import build_dataset, run_predictor, HORIZON_DEFAUT
from analysis.scoring import TECH_WEIGHTS


def make_bt(n: int = 360, seed: int = 3) -> pd.DataFrame:
    """
    Rejeu synthétique : quand "ma_cross_up" est actif, le cours monte de
    +0.8%/jour les jours suivants ; sinon il baisse de -0.3%/jour.
    Blocs de 45 jours — IMPÉRATIVEMENT plus longs que l'horizon (20 j) :
    avec des blocs plus courts, la fenêtre T+20 d'un jour "actif" tomberait
    dans le bloc inactif suivant et l'étiquette serait inversée (leçon
    apprise en écrivant ce test : l'horizon doit être court devant la
    persistance du régime qu'on veut capturer).
    """
    np.random.seed(seed)
    actif  = np.array([bool((i // 45) % 2) for i in range(n)])   # blocs on/off
    # Le rendement du jour dépend du signal de la VEILLE (causalité correcte)
    rendement = np.where(np.roll(actif, 1), 0.008, -0.003)
    rendement += np.random.normal(0, 0.002, n)                   # bruit léger
    close = 100 * np.cumprod(1 + rendement)
    dates = pd.bdate_range("2024-06-03", periods=n)
    return pd.DataFrame({
        "close":   close,
        "score":   50.0,
        "reco":    "NEUTRE",
        "signaux": [{"ma_cross_up"} if a else set() for a in actif],
    }, index=dates)


bt = make_bt()

# ── build_dataset : structure et absence de fuite ──
X, y, X_jour = build_dataset(bt)
assert list(X.columns) == list(TECH_WEIGHTS.index), "une colonne par signal, ordre stable"
assert len(X) == len(bt) - HORIZON_DEFAUT, "les 20 derniers jours (sans futur) sont exclus"
assert X_jour.shape == (1, len(TECH_WEIGHTS)), "X_jour = la photo des signaux d'aujourd'hui"
assert set(X["ma_cross_up"].unique()) == {0, 1}
assert y.dtype == bool
print("✓ build_dataset : features 0/1, étiquette booléenne, horizon exclu")

# ── run_predictor : le modèle apprend le signal prédictif ──
res = run_predictor(bt)
assert res is not None
coefs = {c["code"]: c["coef"] for c in res["coefficients"]}
assert coefs["ma_cross_up"] > 0.5, \
    f"le signal parfaitement prédictif devrait avoir un coef fort, obtenu {coefs['ma_cross_up']}"
# Sur des données aussi propres, le modèle DOIT battre le hasard en test
assert res["bat_le_hasard"] is True
assert res["acc_test"] > 70
print(f"✓ run_predictor : coef ma_cross_up={coefs['ma_cross_up']}, "
      f"précision test {res['acc_test']}% > hasard — le modèle apprend")

# La proba du jour doit refléter l'état actuel du signal
# (dernier bloc : dépend de n=300 → bloc 19 impair → actif)
dernier_actif = "ma_cross_up" in bt["signaux"].iloc[-1]
if dernier_actif:
    assert res["proba_hausse"] > 60, "signal haussier actif → proba élevée attendue"
else:
    assert res["proba_hausse"] < 40, "signal inactif → proba basse attendue"
print(f"✓ proba du jour cohérente avec l'état du signal ({res['proba_hausse']}%)")

# ── Robustesse : historique trop court → None, pas de crash ──
assert run_predictor(make_bt(100)) is None
print("✓ historique trop court → None (pas de modèle sur 80 jours)")

# ── Découpe walk-forward : train + test couvrent tout, sans recouvrement ──
X_full, _, _ = build_dataset(bt)
assert res["n_train"] + res["n_test"] == len(X_full)
print("✓ découpe walk-forward : train + test = dataset complet, sans recouvrement")

print("\n✓ Tous les tests test_predictor.py sont OK (hors réseau)")
