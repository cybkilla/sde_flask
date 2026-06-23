 # module data/market.py complet : cours historiques, indicateurs techniques, données fondamentales, nom du CEO.

# data/market.py
import yfinance as yf
import pandas as pd
import ta
"""
The ta library in Python is a popular open-source package for technical analysis of financial time series data.
It’s built on top of Pandas and NumPy, and provides ready-to-use indicators like RSI, MACD, Bollinger Bands, EMA, etc.
"""
# #import config as cfg
# import sys
# import os

# # Get the absolute path to the directory above the current file ( afin de pouvoir importer les config dans config.py)
# parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add parent directory to sys.path if not already present
# if parent_dir not in sys.path:
#     sys.path.insert(0, parent_dir)

# #print(sys.path)

from config import RSI_PERIOD, MA_SHORT, MA_LONG, HISTORY_DAYS


def get_market_data(ticker: str) -> dict:
    """******************************************************************************
    Fonction qui récupère toutes les données marché pour un ticker via l'api yfinance.
    Retourne un dict structuré prêt pour le scoring.
    ******************************************************************************"""
    try:
        stock = yf.Ticker(ticker)
        hist  = stock.history(period=HISTORY_DAYS)

        if hist.empty:
            raise ValueError(f"Ticker '{ticker}' introuvable ou sans données.")

        # ── Indicateurs techniques ───────────────────────
        close = hist["Close"]

        rsi_ind = ta.momentum.RSIIndicator(close, window=RSI_PERIOD)
        hist["RSI"]  = rsi_ind.rsi()
        hist["MA20"] = close.rolling(MA_SHORT).mean()
        hist["MA50"] = close.rolling(MA_LONG).mean()

        # MACD bonus
        macd = ta.trend.MACD(close)
        hist["MACD"]        = macd.macd()
        hist["MACD_signal"] = macd.macd_signal()

        # Bandes de Bollinger
        bb = ta.volatility.BollingerBands(close)
        hist["BB_upper"] = bb.bollinger_hband()
        hist["BB_lower"] = bb.bollinger_lband()

        # Variations
        var_1d  = (close.iloc[-1] / close.iloc[-2]  - 1) * 100
        var_5d  = (close.iloc[-1] / close.iloc[-5]  - 1) * 100
        var_30d = (close.iloc[-1] / close.iloc[-30] - 1) * 100

        # Volume anormal
        vol_moy = hist["Volume"].rolling(20).mean().iloc[-1]
        vol_now = hist["Volume"].iloc[-1]
        vol_ratio = vol_now / vol_moy if vol_moy > 0 else 1

        # ── Fondamentaux ─────────────────────────────────
        info = stock.info

        #print('INFO : ',info)

        # TODO : Ajouter dans la page d'accueil le descriptif de la compagnie après que le ticker ait été identifié
        print('************longBusinessSummary************ : ', info.get("longBusinessSummary"))

        # ── Dirigeants ───────────────────────────────────
        officers = info.get("companyOfficers", [])
        def find_officer(role_keyword):
            return next(
                (o["name"] for o in officers
                 if role_keyword.upper() in o.get("title", "").upper()),
                "N/A"
            )

        return {
            # Prix
            "ticker":        ticker.upper(),
            "company_name":  info.get("longName", ticker),
            "price":         round(close.iloc[-1], 2),
            "var_1d":        round(var_1d, 2),
            "var_5d":        round(var_5d, 2),
            "var_30d":       round(var_30d, 2),
            # Indicateurs techniques
            "rsi":           round(hist["RSI"].iloc[-1], 1),
            "ma20":          round(hist["MA20"].iloc[-1], 2),
            "ma50":          round(hist["MA50"].iloc[-1], 2),
            "macd":          round(hist["MACD"].iloc[-1], 3),
            "vol_ratio":     round(vol_ratio, 2),
            "history":       hist,
            # Fondamentaux
            "pe_ratio":      info.get("trailingPE"),
            "eps":           info.get("trailingEps"),
            "debt_equity":   info.get("debtToEquity"),
            "revenue_growth":info.get("revenueGrowth"),
            "market_cap":    info.get("marketCap"),
            "sector":        info.get("sector", "N/A"),
            # Dirigeants
            "ceo_name":      find_officer("CEO"),
            "cfo_name":      find_officer("CFO"),
            "officers":      officers,
        }

    except Exception as e:
        raise ValueError(f"Erreur lors de la récupération de '{ticker}': {e}")

#result_df = get_market_data('TMC')
#print(result_df)

