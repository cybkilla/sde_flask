# analysis/signals.py
# Calcul de tous les signaux techniques binaires.
# Chaque signal est un booléen dans une pd.Series.
# Ce module est appelé par scoring.py.

import pandas as pd


def compute_tech_signals(hist: pd.DataFrame) -> pd.Series:
    """
    Reçoit le DataFrame OHLCV enrichi (depuis indicators.py).
    Retourne une pd.Series booléenne indexée par nom de signal.

    Seuls les signaux à True contribueront au score.
    L'approche pd.Series permet à scoring.py d'utiliser
    .reindex() et .sum() sans boucle Python.
    """
    # Dernière ligne du DataFrame = état actuel du marché
    last = hist.iloc[-1]

    rsi  = last["RSI"]
    ma20 = last["MA20"]
    ma50 = last["MA50"]
    macd = last["MACD"]
    msig = last["MACD_sig"]
    vol  = last["Vol_ratio"]   # volume relatif pré-calculé
    ret5 = last["Ret_5d"]       # variation 5j en % (pct_change)
    prix = last["Close"]
    bbu  = last["BB_upper"]
    bbl  = last["BB_lower"]

    # --- Signaux RSI (4 zones mutuellement exclusives) -----
    # On utilise pd.isna() pour gérer les NaN proprement
    rsi_ok = pd.notna(rsi)
    s_rsi_survente = rsi_ok and rsi < 30
    s_rsi_bas      = rsi_ok and 30 <= rsi < 45
    s_rsi_haut     = rsi_ok and 55 < rsi <= 70
    s_rsi_surachat = rsi_ok and rsi > 70

    # --- Croisement des moyennes mobiles ------------------
    # Vrai si MA20 est au-dessus de MA50 (tendance haussière)
    ma_ok      = pd.notna(ma20) and pd.notna(ma50)
    s_ma_up    = ma_ok and ma20 > ma50
    s_ma_down  = ma_ok and ma20 <= ma50

    # --- MACD vs ligne de signal --------------------------
    macd_ok    = pd.notna(macd) and pd.notna(msig)
    s_macd_bull= macd_ok and macd > msig   # momentum positif
    s_macd_bear= macd_ok and macd <= msig  # momentum négatif

    # --- Volume anormal -----------------------------------
    # Vol_ratio > 2 signifie volume 2x supérieur à la moyenne
    s_vol_anormal = pd.notna(vol) and vol > 2.0

    # --- Position vs bandes de Bollinger -----------------
    bb_ok        = pd.notna(bbu) and pd.notna(bbl)
    s_bb_haut    = bb_ok and prix > bbu   # surachat potentiel
    s_bb_bas     = bb_ok and prix < bbl   # survente potentielle

    # --- Tendance 5 jours (Ret_5d = pct_change(5) Pandas) -
    ret5_ok         = pd.notna(ret5)
    s_trend_fort    = ret5_ok and ret5 > 5
    s_trend_mod     = ret5_ok and 2 < ret5 <= 5
    s_trend_neg     = ret5_ok and ret5 < -5
    s_trend_neg_mod = ret5_ok and -5 <= ret5 < -2

    # --- Retour sous forme de pd.Series booléenne ---------
    # Le nom de chaque clé doit correspondre exactement
    # aux clés du dict `weights` dans scoring.py
    return pd.Series({
        "rsi_survente":    s_rsi_survente,
        "rsi_bas":         s_rsi_bas,
        "rsi_haut":        s_rsi_haut,
        "rsi_surachat":    s_rsi_surachat,
        "ma_cross_up":     s_ma_up,
        "ma_cross_down":   s_ma_down,
        "macd_bull":       s_macd_bull,
        "macd_bear":       s_macd_bear,
        "vol_anormal":     s_vol_anormal,
        "prix_bb_haut":    s_bb_haut,
        "prix_bb_bas":     s_bb_bas,
        "trend_5j_fort":   s_trend_fort,
        "trend_5j_mod":    s_trend_mod,
        "trend_5j_neg":    s_trend_neg,
        "trend_5j_neg_mod":s_trend_neg_mod,
    }, dtype=bool)
