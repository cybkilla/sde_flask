# data/market.py — yfinance (primaire) → Finnhub + Twelve Data (fallback cloud)
import os
import time
import pandas as pd
from utils.indicators import add_indicators
from config import HISTORY_DAYS

# ── Helpers communs ───────────────────────────────────────
def _safe(val, default=None):
    if val is None:
        return default
    try:
        return default if pd.isna(val) else val
    except Exception:
        return val


def _build_ret_vol(hist: pd.DataFrame) -> pd.DataFrame:
    """Ajoute Ret_1d/5d/30d et Vol_ratio sur un DataFrame clôturé."""
    h = hist.copy()
    c = h["Close"]
    h["Ret_1d"]    = c.pct_change(1)  * 100
    h["Ret_5d"]    = c.pct_change(5)  * 100
    h["Ret_30d"]   = c.pct_change(30) * 100
    h["Vol_ratio"] = (h["Volume"] / h["Volume"].rolling(20).mean()).round(2)
    return h


def _ind_fn(last: pd.Series, live_price: float):
    """Retourne une fonction _ind(col, default, digits) sur la dernière ligne."""
    def _ind(col, default, digits=2):
        try:
            v = float(last[col])
            return round(v, digits) if not pd.isna(v) else default
        except Exception:
            return default
    return _ind


# ══════════════════════════════════════════════════════════
# SOURCE A — yfinance (primaire)
# ══════════════════════════════════════════════════════════
def _get_yfinance(ticker: str) -> dict:
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    def _find_officer(officers, role):
        return next(
            (o["name"] for o in officers if role.upper() in o.get("title", "").upper()),
            "N/A",
        )

    stock = yf.Ticker(ticker)

    hist = pd.DataFrame()
    for period in [HISTORY_DAYS, "30d", "5d", "1d"]:
        try:
            hist = stock.history(period=period)
        except YFRateLimitError:
            raise
        if not hist.empty:
            break

    if hist.empty:
        # Tentative de résolution automatique (ex. "SMSN" → "SMSN.IL")
        try:
            from utils.ticker_search import search_tickers
            df = search_tickers(ticker, max_results=5)
            if not df.empty:
                resolved = str(df.iloc[0]["ticker"])
                if resolved != ticker:
                    stock  = yf.Ticker(resolved)
                    ticker = resolved
                    for period in [HISTORY_DAYS, "5d", "1d"]:
                        hist = stock.history(period=period)
                        if not hist.empty:
                            break
        except Exception:
            pass

    if hist.empty:
        raise ValueError(f"Ticker '{ticker}' introuvable ou sans données.")

    hist = hist.rename_axis("Date").pipe(add_indicators)
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise ValueError(f"Ticker '{ticker}' : aucune clôture disponible.")

    hist = _build_ret_vol(hist)
    last = hist.iloc[-1]
    _ind = _ind_fn(last, 0)

    info       = stock.info
    officers   = info.get("companyOfficers", [])
    live_price = _safe(info.get("regularMarketPrice") or info.get("currentPrice"))
    prev_close = _safe(info.get("regularMarketPreviousClose") or info.get("previousClose"))
    pre_market = _safe(info.get("preMarketPrice"))
    post_market= _safe(info.get("postMarketPrice"))

    if live_price and prev_close:
        var_1d = round((live_price - prev_close) / prev_close * 100, 2)
    else:
        live_price = round(float(last["Close"]), 2)
        var_1d     = round(float(last["Ret_1d"]), 2)

    _ind = _ind_fn(last, live_price)

    return {
        "ticker":         ticker,
        "company_name":   info.get("longName", ticker),
        "sector":         info.get("sector",   "N/A"),
        "industry":       info.get("industry", "N/A"),
        "currency":       info.get("currency", "USD"),
        "price":          round(live_price, 2),
        "prev_close":     round(prev_close, 2)  if prev_close  else None,
        "pre_market":     round(pre_market, 2)  if pre_market  else None,
        "post_market":    round(post_market, 2) if post_market else None,
        "var_1d":         var_1d,
        "var_5d":         _ind("Ret_5d",  0.0),
        "var_30d":        _ind("Ret_30d", 0.0),
        "rsi":            _ind("RSI",      50.0, digits=1),
        "ma20":           _ind("MA20",     live_price),
        "ma50":           _ind("MA50",     live_price),
        "macd":           _ind("MACD",     0.0, digits=4),
        "macd_signal":    _ind("MACD_sig", 0.0, digits=4),
        "bb_upper":       _ind("BB_upper", round(live_price * 1.05, 2)),
        "bb_lower":       _ind("BB_lower", round(live_price * 0.95, 2)),
        "vol_ratio":      _ind("Vol_ratio", 1.0),
        "pe_ratio":       _safe(info.get("trailingPE")),
        "eps":            _safe(info.get("trailingEps")),
        "debt_equity":    _safe(info.get("debtToEquity")),
        "revenue_growth": _safe(info.get("revenueGrowth")),
        "market_cap":     _safe(info.get("marketCap")),
        "dividend_yield": _safe(info.get("dividendYield")),
        "ceo_name":       _find_officer(officers, "CEO"),
        "cfo_name":       _find_officer(officers, "CFO"),
        "officers":       officers,
        "history":        hist,
    }


# ══════════════════════════════════════════════════════════
# SOURCE B — Finnhub (quote/fondamentaux) + Twelve Data (OHLCV)
#            Fallback cloud quand Yahoo Finance est bloqué
# ══════════════════════════════════════════════════════════
import re

_fh_client = None


def _fh():
    global _fh_client
    if _fh_client is None:
        api_key = os.getenv("FINNHUB_API_KEY", "")
        if not api_key:
            raise RuntimeError("FINNHUB_API_KEY absent")
        import finnhub
        _fh_client = finnhub.Client(api_key=api_key)
    return _fh_client


def _period_to_days(period: str) -> int:
    m = re.match(r"(\d+)(d|w|mo|m|y)", period.lower())
    if not m:
        return 90
    n, unit = int(m.group(1)), m.group(2)
    return n * {"d": 1, "w": 7, "mo": 30, "m": 30, "y": 365}.get(unit, 1)


def _get_candles_td(ticker: str, days: int) -> pd.DataFrame:
    api_key = os.getenv("TWELVE_DATA_API_KEY", "")
    if not api_key:
        raise RuntimeError("TWELVE_DATA_API_KEY absent")
    from twelvedata import TDClient
    td = TDClient(apikey=api_key, timeout=12)
    try:
        ts = td.time_series(
            symbol=ticker, interval="1day",
            outputsize=min(days, 5000), order="ASC",
        ).as_pandas()
    except Exception as e:
        print(f"[Market] Twelve Data erreur ({ticker}) [{type(e).__name__}]: {e}", flush=True)
        return pd.DataFrame()

    if ts is None or ts.empty:
        print(f"[Market] Twelve Data réponse vide pour {ticker}", flush=True)
        return pd.DataFrame()

    ts.index = pd.to_datetime(ts.index)
    ts.index.name = "Date"
    ts = ts.rename(columns={"open": "Open", "high": "High",
                             "low": "Low", "close": "Close", "volume": "Volume"})
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in ts.columns:
            ts[col] = pd.to_numeric(ts[col], errors="coerce")
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in ts.columns]
    return ts[cols].dropna(subset=["Close"]).sort_index()


def _get_finnhub_fallback(ticker: str) -> dict:
    fh   = _fh()
    days = _period_to_days(HISTORY_DAYS)

    hist = _get_candles_td(ticker, days)
    if hist.empty and days > 30:
        hist = _get_candles_td(ticker, 30)
    if hist.empty:
        raise ValueError(f"Ticker '{ticker}' introuvable ou sans données.")

    hist = hist.rename_axis("Date").pipe(add_indicators)
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise ValueError(f"Ticker '{ticker}' : aucune clôture disponible.")

    hist = _build_ret_vol(hist)
    last = hist.iloc[-1]

    # Quote temps réel
    try:
        quote = fh.quote(ticker) or {}
    except Exception:
        quote = {}
    live_price = _safe(quote.get("c")) or round(float(last["Close"]), 2)
    prev_close = _safe(quote.get("pc"))

    if live_price and prev_close:
        var_1d = round((live_price - prev_close) / prev_close * 100, 2)
    else:
        var_1d = 0.0
    live_price = round(float(live_price), 2)

    _ind = _ind_fn(last, live_price)

    # Profil
    try:
        profile = fh.company_profile2(symbol=ticker) or {}
    except Exception:
        profile = {}

    # Fondamentaux
    try:
        metrics = (fh.company_basic_financials(ticker, "all") or {}).get("metric", {})
    except Exception:
        metrics = {}

    pe  = _safe(metrics.get("peBasicExclExtraTTM") or metrics.get("peTTM"))
    eps = _safe(metrics.get("epsBasicExclExtraTTM") or metrics.get("epsNormalizedAnnual"))
    de  = _safe(metrics.get("totalDebt/totalEquityAnnual") or metrics.get("longTermDebt/equityAnnual"))
    mktcap_m = metrics.get("marketCapitalization") or profile.get("marketCapitalization")

    # Dirigeants
    try:
        persons  = (fh.company_executives(ticker) or {}).get("executive", []) or []
        ceo_name = next((p.get("name","N/A") for p in persons if "CEO" in p.get("title","").upper()), "N/A")
        cfo_name = next((p.get("name","N/A") for p in persons if "CFO" in p.get("title","").upper()), "N/A")
    except Exception:
        ceo_name = cfo_name = "N/A"

    return {
        "ticker":         ticker,
        "company_name":   profile.get("name") or ticker,
        "sector":         profile.get("finnhubIndustry") or "N/A",
        "industry":       profile.get("finnhubIndustry") or "N/A",
        "currency":       profile.get("currency") or "USD",
        "price":          live_price,
        "prev_close":     round(float(prev_close), 2) if prev_close else None,
        "pre_market":     None,
        "post_market":    None,
        "var_1d":         var_1d,
        "var_5d":         _ind("Ret_5d",  0.0),
        "var_30d":        _ind("Ret_30d", 0.0),
        "rsi":            _ind("RSI",      50.0, digits=1),
        "ma20":           _ind("MA20",     live_price),
        "ma50":           _ind("MA50",     live_price),
        "macd":           _ind("MACD",     0.0, digits=4),
        "macd_signal":    _ind("MACD_sig", 0.0, digits=4),
        "bb_upper":       _ind("BB_upper", round(live_price * 1.05, 2)),
        "bb_lower":       _ind("BB_lower", round(live_price * 0.95, 2)),
        "vol_ratio":      _ind("Vol_ratio", 1.0),
        "pe_ratio":       pe,
        "eps":            eps,
        "debt_equity":    de,
        "revenue_growth": _safe(metrics.get("revenueGrowthTTMYoy")),
        "market_cap":     _safe(mktcap_m and mktcap_m * 1_000_000),
        "dividend_yield": _safe(metrics.get("dividendYieldIndicatedAnnual") or metrics.get("dividendYield5Y")),
        "ceo_name":       ceo_name,
        "cfo_name":       cfo_name,
        "officers":       [],
        "history":        hist,
    }


# ══════════════════════════════════════════════════════════
# POINT D'ENTRÉE — essaie yfinance, bascule sur Finnhub+TD
# ══════════════════════════════════════════════════════════
def get_market_data(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    try:
        return _get_yfinance(ticker)
    except Exception as e:
        print(f"[Market] yfinance indisponible pour {ticker} ({e}) — bascule Finnhub+TwelveData")
        return _get_finnhub_fallback(ticker)
