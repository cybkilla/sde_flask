# tests/test_backtest.py — tests unitaires du module de backtest, hors réseau.
#
# Principe : on fabrique un historique OHLCV synthétique (marche aléatoire
# avec graine fixe → résultats reproductibles), on l'injecte à la place du
# téléchargement yfinance, et on vérifie la mécanique du backtest :
# absence de look-ahead, cohérence des stats, bornes des scores.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from analysis import backtest as bt_mod
from analysis.backtest import (
    _enrich, _replay_scores, _stats_par_action, _equity_curve,
    _attribution_par_signal, run_backtest, WARMUP_DAYS,
)


def make_hist(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """
    Génère n jours d'OHLCV synthétique.
    np.random.seed fige le générateur → chaque exécution du test
    produit exactement les mêmes prix (test déterministe).
    """
    np.random.seed(seed)
    close = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.015, n))
    dates = pd.bdate_range("2024-01-02", periods=n)   # jours ouvrés uniquement
    return pd.DataFrame({
        "Open":   close * (1 + np.random.normal(0, 0.003, n)),
        "High":   close * 1.01,
        "Low":    close * 0.99,
        "Close":  close,
        "Volume": np.random.randint(1_000_000, 5_000_000, n).astype(float),
    }, index=dates)


# ── _enrich : toutes les colonnes attendues par compute_tech_signals ──
hist = _enrich(make_hist())
for col in ["RSI", "MA20", "MA50", "MACD", "MACD_sig",
            "BB_upper", "BB_lower", "Ret_5d", "Vol_ratio"]:
    assert col in hist.columns, f"colonne manquante après _enrich : {col}"
print("✓ _enrich produit toutes les colonnes nécessaires")


# ── _replay_scores : bornes, warm-up et absence de look-ahead ──
bt = _replay_scores(hist)

# Le warm-up saute les 50 premiers jours (MA50 indisponible avant)
assert len(bt) == len(hist) - WARMUP_DAYS
assert bt["score"].between(0, 100).all(), "score hors bornes 0-100"
assert set(bt["reco"].unique()) <= {"ACHETER", "VENDRE", "NEUTRE"}

# Anti-look-ahead : le score du jour T ne doit PAS changer si on ajoute
# des jours APRÈS T. On rejoue sur un historique tronqué et on compare.
bt_court = _replay_scores(hist.iloc[:120])
commun   = bt_court.index.intersection(bt.index)
pd.testing.assert_series_equal(
    bt.loc[commun, "score"], bt_court.loc[commun, "score"],
    check_names=False,
)
print(f"✓ _replay_scores : {len(bt)} jours, scores bornés, aucun look-ahead")


# ── _stats_par_action : cohérence des compteurs ──
stats = _stats_par_action(bt, horizons=(5, 20))
for h in ("5", "20"):
    total = sum(s["n"] for s in stats[h].values())
    # Les h derniers jours n'ont pas de "futur" à mesurer (shift(-h) → NaN)
    assert total == len(bt) - int(h), f"compteur incohérent à l'horizon {h}j"
    for action, s in stats[h].items():
        if s["hit_pct"] is not None:
            assert 0 <= s["hit_pct"] <= 100
print("✓ _stats_par_action : compteurs et pourcentages cohérents")


# ── _equity_curve : base 100 et décalage d'exécution ──
curve = _equity_curve(bt)
assert curve["strategie"][0] == 100.0, "la courbe doit démarrer à 100"
assert curve["buy_hold"][0]  == 100.0
assert len(curve["dates"]) == len(bt)
# Le buy & hold doit refléter exactement la variation totale du cours
attendu = (bt["close"].iloc[-1] / bt["close"].iloc[0] - 1) * 100
assert abs(curve["bh_pct"] - attendu) < 0.1, "buy & hold ≠ variation réelle du cours"
print("✓ _equity_curve : base 100 et buy & hold exacts")


# ── _attribution_par_signal : logique d'épisodes et de sens ──
# On construit un mini-DataFrame à la main pour contrôler exactement
# les épisodes : "ma_cross_up" (+15, haussier) actif jours 2-4 puis jour 8
# → 2 épisodes, mesurés aux jours 2 et 8.
n = 40
dates  = pd.bdate_range("2025-01-02", periods=n)
close  = pd.Series(np.linspace(100, 140, n), index=dates)  # hausse régulière
sig    = [set() for _ in range(n)]
for j in [2, 3, 4, 8]:
    sig[j].add("ma_cross_up")       # 2 épisodes haussiers (marché qui monte)
for j in [10, 11, 12]:
    sig[j].add("rsi_surachat")      # 1 épisode baissier (marché qui monte quand même)
bt_manuel = pd.DataFrame({"close": close, "signaux": sig})

attrib = _attribution_par_signal(bt_manuel, horizon=5)
par_code = {a["code"]: a for a in attrib}

# ma_cross_up : 2 épisodes distincts (les jours 3-4 consécutifs ne comptent pas)
assert par_code["ma_cross_up"]["n_episodes"] == 2
assert par_code["ma_cross_up"]["n_jours"]    == 4
# Signal haussier + cours qui monte → 100% de réussite
assert par_code["ma_cross_up"]["hit_pct"] == 100.0

# rsi_surachat : signal BAISSIER mais le cours monte → 0% de réussite
assert par_code["rsi_surachat"]["n_episodes"] == 1
assert par_code["rsi_surachat"]["hit_pct"] == 0.0

# Tri : les moins fiables d'abord
assert attrib[0]["hit_pct"] <= attrib[-1]["hit_pct"]
print("✓ _attribution_par_signal : épisodes, sens et tri corrects")


# ── signaux_compacts (advisor) : extraction du vecteur de signaux ──
from portfolio.advisor import signaux_compacts
snap = {"signals_tech": [
    {"code": "ma_cross_up", "nom": "Croisement haussier MA20 > MA50", "points": 15},
    {"nom": "Ancien snapshot sans code", "points": -8},   # rétro-compatibilité
]}
sc = signaux_compacts(snap)
assert sc == {"ma_cross_up": 15, "Ancien snapshot sans code": -8}
assert signaux_compacts({}) == {}          # snapshot vide → dict vide, pas de crash
print("✓ signaux_compacts : codes extraits, rétro-compatible, robuste au vide")


# ── run_backtest de bout en bout (yfinance remplacé par le synthétique) ──
# Monkey-patching : on substitue la fonction réseau par notre générateur.
# C'est la technique standard pour tester sans dépendance externe.
bt_mod._fetch_history = lambda ticker, period="2y": make_hist(300)
res = run_backtest("FAKE", use_cache=False)
assert res["ok"] is True
assert res["n_jours"] == 300 - WARMUP_DAYS
assert "5" in res["stats"] and "20" in res["stats"]
assert "note" in res            # la limite méthodologique doit être exposée
assert "attribution" in res and len(res["attribution"]) > 0
assert all("hit_pct" in a and "n_episodes" in a for a in res["attribution"])
print("✓ run_backtest bout en bout OK (hors réseau)")

# Historique trop court → ValueError explicite, pas de crash silencieux
bt_mod._fetch_history = lambda ticker, period="2y": make_hist(60)
try:
    run_backtest("FAKE2", use_cache=False)
    raise AssertionError("un historique de 60 jours aurait dû être refusé")
except ValueError:
    print("✓ historique trop court correctement refusé")

print("\n✓ Tous les tests test_backtest.py sont OK (hors réseau)")
