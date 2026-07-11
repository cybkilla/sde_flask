# tests/test_risk.py — tests de la normalisation ATR des seuils, hors réseau.
#
# atr_pct(), seuils_adaptes() et drawdown_depuis_plus_haut() sont des
# fonctions PURES : historiques OHLC synthétiques à volatilité contrôlée.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from portfolio.risk import (
    atr_pct, seuils_adaptes, drawdown_depuis_plus_haut,
    SL_ATR_MULT, TP_ATR_MULT,
)


def make_ohlc(vol_quotidienne: float, n: int = 60, seed: int = 5) -> pd.DataFrame:
    """
    Historique OHLC synthétique dont l'amplitude quotidienne (haut-bas)
    est contrôlée : vol_quotidienne = 0.05 → chaque bougie fait ~5% du cours.
    """
    np.random.seed(seed)
    close = pd.Series(100 * np.cumprod(1 + np.random.normal(0, vol_quotidienne / 3, n)))
    dates = pd.bdate_range("2026-04-01", periods=n)
    return pd.DataFrame({
        "Close": close.values,
        "High":  close.values * (1 + vol_quotidienne / 2),
        "Low":   close.values * (1 - vol_quotidienne / 2),
    }, index=dates)


CFG = {"stop_loss_pct": -20.0, "take_profit_pct": 15.0, "pnl_renforcer": -5.0}


# ── atr_pct : mesure bien l'amplitude quotidienne ──
atr_volatil = atr_pct(make_ohlc(0.05))   # bougies ~5%
atr_calme   = atr_pct(make_ohlc(0.01))   # bougies ~1%
assert 4.0 < atr_volatil < 7.0, f"ATR titre volatil attendu ~5%, obtenu {atr_volatil}"
assert 0.8 < atr_calme  < 1.5, f"ATR titre calme attendu ~1%, obtenu {atr_calme}"
# Historique trop court ou None → None (fallback seuils config)
assert atr_pct(make_ohlc(0.05, n=10)) is None
assert atr_pct(None) is None
print(f"✓ atr_pct : volatil {atr_volatil}%, calme {atr_calme}%, robuste aux cas limites")


# ── seuils_adaptes : le même titre volatil / calme donne des seuils opposés ──
s_vol   = seuils_adaptes(CFG, atr_volatil)
s_calme = seuils_adaptes(CFG, atr_calme)

# Titre volatil : stop = 2.5×ATR ≈ -13%, plus serré que la config -20
assert s_vol["adapte"] is True
assert abs(s_vol["stop_loss_pct"] - (-SL_ATR_MULT * atr_volatil)) < 0.1
assert -20 < s_vol["stop_loss_pct"] < -8

# Titre calme : 2.5×1% = -2.5 → borné au plancher 40% de la config (-8)
assert s_calme["stop_loss_pct"] == -8.0, f"attendu -8 (borne), obtenu {s_calme['stop_loss_pct']}"

# Le stop du titre calme est TOUJOURS plus serré que celui du volatil
assert s_calme["stop_loss_pct"] > s_vol["stop_loss_pct"]

# Jamais plus large que la config (perte max choisie par l'utilisateur)
s_extreme = seuils_adaptes(CFG, 15.0)   # ATR délirant de 15%/jour
assert s_extreme["stop_loss_pct"] >= -20.0

# Sans ATR → config inchangée, drapeau adapte=False
s_none = seuils_adaptes(CFG, None)
assert s_none["adapte"] is False and s_none["stop_loss_pct"] == -20.0
print("✓ seuils_adaptes : ATR appliqué, bornés autour de la config, fallback propre")


# ── drawdown_depuis_plus_haut : le trailing voit ce que le P&L ne voit pas ──
# Cours : monte de 100 à 140 puis retombe à 120 — position achetée à 100.
# P&L vs entrée : +20% (« tout va bien ») ; drawdown vs sommet : -14.3%.
n = 40
montee   = np.linspace(100, 140, 25)
descente = np.linspace(140, 120, 15)
close    = np.concatenate([montee, descente])
hist_dd  = pd.DataFrame(
    {"Close": close, "High": close * 1.01, "Low": close * 0.99},
    index=pd.bdate_range("2026-05-01", periods=n),
)
lots = [{"type": "achat", "date_achat": "2026-05-01"}]

hwm, dd = drawdown_depuis_plus_haut(hist_dd, lots, prix=120.0)
assert hwm == 140.0, f"plus haut attendu 140, obtenu {hwm}"
assert abs(dd - (-14.29)) < 0.1, f"drawdown attendu -14.3%, obtenu {dd}"

# Achat APRÈS le sommet → le plus haut est celui de la fenêtre de détention
hwm2, dd2 = drawdown_depuis_plus_haut(hist_dd, [{"type": "achat", "date_achat": "2026-06-19"}], 120.0)
assert hwm2 < 140.0, "le sommet d'avant l'achat ne doit pas compter"

# Le prix live peut être le sommet lui-même → drawdown nul
hwm3, dd3 = drawdown_depuis_plus_haut(hist_dd, lots, prix=145.0)
assert hwm3 == 145.0 and dd3 == 0.0

# Cas limites → (None, None), pas de crash
assert drawdown_depuis_plus_haut(None, lots, 100.0) == (None, None)
assert drawdown_depuis_plus_haut(hist_dd, [], 100.0) == (None, None)
assert drawdown_depuis_plus_haut(hist_dd, [{"type": "vente", "date_achat": "2026-05-02"}], 100.0) == (None, None)
print("✓ drawdown : sommet depuis l'achat, prix live inclus, cas limites propres")


# ── gap_significatif : seuil adapté à la volatilité du titre ──
from portfolio.risk import gap_significatif
# TMC (ATR 6.4) : -5% est du bruit pré-marché, -7% est significatif
assert gap_significatif(-5.0, 6.4) is False
assert gap_significatif(-7.0, 6.4) is True
# Titre calme (ATR 1.2) : le plancher de 2% s'applique
assert gap_significatif(-2.5, 1.2) is True
assert gap_significatif(-1.5, 1.2) is False
# Sans ATR : seuil prudent 3%
assert gap_significatif(2.9, None) is False and gap_significatif(3.1, None) is True
# Gap inconnu → jamais significatif (pas de faux déclenchement)
assert gap_significatif(None, 5.0) is False
print("✓ gap_significatif : seuil max(2%, 1×ATR), prudent sans données")


# ── Ligne Pré-marché dans le raisonnement du conseil ──
from portfolio.advisor import generate_advice
_hist_gap = make_ohlc(0.05)
_market   = {"price": float(_hist_gap["Close"].iloc[-1]), "rsi": 50.0,
             "history": _hist_gap, "gap_overnight": -7.2}
_summary  = {"pnl_pct": 5.0, "total_shares": 100, "cout_moyen": 100.0,
             "lots": [{"type": "achat", "date_achat": "2026-04-01"}]}
_snap     = {"score_global": 50.0, "recommandation": "NEUTRE",
             "signals_tech": [], "signals_fund": []}
adv = generate_advice(_summary, _market, _snap)
assert "Pré-marché : -7.2%" in adv["raisonnement"], "la ligne gap doit apparaître"
assert "baissier" in adv["raisonnement"]
# Sans gap : pas de ligne (la clé absente ne doit rien afficher)
_market.pop("gap_overnight")
adv2 = generate_advice(_summary, _market, _snap)
assert "Pré-marché" not in adv2["raisonnement"]
print("✓ conseil : ligne Pré-marché présente avec gap, absente sans")


# ── Cohérence avec l'évaluateur : bande TENIR vol-normalisée ──
from portfolio.evaluator import _seuil_tenir
assert _seuil_tenir(20) == 13.4                       # sans ATR : base 3% historique
assert _seuil_tenir(20, atr=5.0) == round(5.0 * 20**0.5, 1)   # ±22.4% pour un titre à 5%
assert _seuil_tenir(1, atr=15.0) == 8.0               # ATR extrême borné à 8
assert _seuil_tenir(1, atr=0.5)  == 2.0               # ATR minuscule borné à 2
print("✓ _seuil_tenir : bande TENIR proportionnelle à l'ATR, bornée [2;8]")

print("\n✓ Tous les tests test_risk.py sont OK (hors réseau)")
