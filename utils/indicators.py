# utils/indicators.py — tous les indicateurs en Pandas pur
import pandas as pd
import numpy  as np
from config import RSI_PERIOD, MA_SHORT, MA_LONG

# ── RSI manuel en Pandas (sans librairie externe) ─────
def _rsi_pandas(series: pd.Series, window: int = 14) -> pd.Series:
    """
    Calcul du RSI via Pandas pur.
    Utilise la méthode Wilder (ewm) — identique à TradingView.
    """
    delta = series.diff()

    gain = delta.clip(lower=0)   # ne garde que les hausses
    loss = delta.clip(upper=0).abs()  # ne garde que les baisses

    # Moyenne mobile exponentielle Wilder (alpha = 1/window)
    avg_gain = gain.ewm(alpha=1/window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/window, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.round(2)

# ── MACD en Pandas ────────────────────────────────────
def _macd_pandas(series: pd.Series,
                  fast=12, slow=26, signal=9) -> pd.DataFrame:
    """Retourne un DataFrame avec MACD, Signal et Histogramme."""
    ema_fast   = series.ewm(span=fast,   adjust=False).mean()
    ema_slow   = series.ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line= macd_line.ewm(span=signal, adjust=False).mean()
    histogram  = macd_line - signal_line

    return pd.DataFrame({
        "MACD":     macd_line.round(4),
        "MACD_sig": signal_line.round(4),
        "MACD_hist":histogram.round(4),
    })

# ── Bandes de Bollinger en Pandas ─────────────────────
def _bollinger_pandas(series: pd.Series,
                       window=20, nb_std=2) -> pd.DataFrame:
    """Bandes haute / centrale / basse."""
    ma  = series.rolling(window).mean()
    std = series.rolling(window).std()
    return pd.DataFrame({
        "BB_mid":  ma.round(2),
        "BB_upper":(ma + nb_std * std).round(2),
        "BB_lower":(ma - nb_std * std).round(2),
    })

# ── Fonction .pipe() principale ───────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reçoit le DataFrame OHLCV brut de yfinance.
    Retourne le même DataFrame enrichi de tous les indicateurs.
    Conçu pour être appelé via .pipe(add_indicators).
    """
    close = df["Close"]

    # Moyennes mobiles simples
    df["MA20"] = close.rolling(MA_SHORT).mean().round(2)
    df["MA50"] = close.rolling(MA_LONG).mean().round(2)

    # EMA rapide
    df["EMA9"] = close.ewm(span=9, adjust=False).mean().round(2)

    # RSI (Pandas pur, sans ta-lib)
    df["RSI"]  = _rsi_pandas(close, window=RSI_PERIOD)

    # MACD
    macd_df  = _macd_pandas(close)
    df       = pd.concat([df, macd_df], axis=1)

    # Bandes de Bollinger
    bb_df    = _bollinger_pandas(close)
    df       = pd.concat([df, bb_df], axis=1)

    # Signal croisement MA : True quand MA20 passe au-dessus de MA50
    df["MA_cross_up"] = (
        (df["MA20"] > df["MA50"]) &
        (df["MA20"].shift(1) <= df["MA50"].shift(1))
    )

    return df

def indicateurs_intraday(hist, prix_live: float) -> dict:
    """
    RSI(14) et variation 5 séances recalculés EN SÉANCE : le prix live
    devient la clôture provisoire du jour. Fonction PURE — sert au
    rafraîchissement 60s de la fiche analyse (les tuiles RSI/Var5j
    étaient figées au chargement alors que le prix vivait).
    Le Vol. ratio n'est PAS recalculable : pas de volume temps réel
    sur nos sources gratuites.
    Retourne {} si l'historique est inexploitable.
    """
    import datetime as _dt
    try:
        if hist is None or len(hist) < 15 or not prix_live:
            return {}
        close = hist["Close"].copy()
        # La dernière bougie est-elle celle d'AUJOURD'HUI ? → on la
        # remplace par le prix live ; sinon on ajoute une bougie provisoire
        derniere = str(close.index[-1])[:10]
        prov = close.reset_index(drop=True)     # positionnel : index dates inutile ici
        if derniere == str(_dt.date.today()):
            prov.iloc[-1] = float(prix_live)
        else:
            prov = pd.concat([prov, pd.Series([float(prix_live)])],
                             ignore_index=True)
        out = {"rsi_live": round(float(_rsi_pandas(prov).iloc[-1]), 1)}
        if len(prov) >= 6:
            out["var_5d_live"] = round(
                (float(prov.iloc[-1]) / float(prov.iloc[-6]) - 1) * 100, 2)
        return out
    except Exception:
        return {}
