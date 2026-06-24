# data/market.py — collecte et enrichissement Pandas
import time
import yfinance as yf
import pandas  as pd
from yfinance.exceptions import YFRateLimitError
from utils.indicators import add_indicators
from config import HISTORY_DAYS

# ── Résolution ticker ─────────────────────────────────
def _resolve_ticker(ticker: str) -> str:
    """
    Si le ticker nu (ex. "SMSN") ne retourne aucune donnée,
    interroge Yahoo Search pour trouver le symbole complet
    avec suffix d'exchange (ex. "SMSN.IL").
    Retourne le ticker d'origine si aucune résolution possible.
    """
    try:
        from utils.ticker_search import search_tickers
        df = search_tickers(ticker, max_results=5)
        if not df.empty:
            return str(df.iloc[0]["ticker"])
    except Exception:
        pass
    return ticker


# ── Helpers ───────────────────────────────────────────
def _find_officer(officers: list, role: str) -> str:
    """Cherche un dirigeant par rôle dans la liste yfinance."""
    return next(
        (o["name"] for o in officers
         if role.upper() in o.get("title", "").upper()),
        "N/A"
    )

def _safe(val, default=None):
    """Retourne None si la valeur est NaN ou absente."""
    if val is None: return default
    try:
        return default if pd.isna(val) else val
    except:
        return val

# ── Fonction principale ───────────────────────────────
def get_market_data(ticker: str, _attempt: int = 0) -> dict:
    """
    Collecte toutes les données marché via yfinance.
    Retourne un dict avec :
      - 'history' : DataFrame enrichi (OHLCV + indicateurs)
      - clés scalaires pour le scoring et l'affichage
    Retry automatique (2×) si Yahoo Finance renvoie un 429.
    """
    ticker = ticker.upper().strip()
    try:
        stock = yf.Ticker(ticker)
    except YFRateLimitError:
        if _attempt < 2:
            time.sleep(5 * (_attempt + 1))
            return get_market_data(ticker, _attempt + 1)
        raise

    # ── 1. Données brutes → DataFrame ─────────────────
    # Fallback sur des périodes plus courtes pour les tickers récents
    hist: pd.DataFrame = pd.DataFrame()
    for period in [HISTORY_DAYS, "30d", "5d", "1d"]:
        try:
            hist = stock.history(period=period)
        except YFRateLimitError:
            if _attempt < 2:
                print(f"[Market] Rate limit yfinance — attente {5*(_attempt+1)}s…")
                time.sleep(5 * (_attempt + 1))
                return get_market_data(ticker, _attempt + 1)
            raise
        if not hist.empty:
            break

    # Résolution automatique si le ticker nu ne retourne rien
    # (ex. "SMSN" → "SMSN.IL", "005930" → "005930.KS")
    if hist.empty:
        resolved = _resolve_ticker(ticker)
        if resolved != ticker:
            stock  = yf.Ticker(resolved)
            ticker = resolved
            for period in [HISTORY_DAYS, "5d", "1d"]:
                hist = stock.history(period=period)
                if not hist.empty:
                    break

    if hist.empty:
        raise ValueError(f"Ticker '{ticker}' introuvable ou sans données.")

    # ── 2. Calcul Pandas : variations + indicateurs ───
    hist = (
        hist
        .rename_axis("Date")
        .pipe(add_indicators)
    )

    # Élimine les lignes sans clôture (séance en cours non clôturée)
    hist_closed = hist.dropna(subset=["Close"])
    if hist_closed.empty:
        raise ValueError(f"Ticker '{ticker}' : aucune clôture disponible.")

    # Variations en % calculées sur les clôtures réelles uniquement
    close = hist_closed["Close"]
    hist_closed = hist_closed.copy()
    hist_closed["Ret_1d"]  = close.pct_change(1)  * 100
    hist_closed["Ret_5d"]  = close.pct_change(5)  * 100
    hist_closed["Ret_30d"] = close.pct_change(30) * 100
    hist_closed["Vol_ratio"] = (
        hist_closed["Volume"] / hist_closed["Volume"].rolling(20).mean()
    ).round(2)
    # Réintègre dans hist pour que les graphiques aient toutes les colonnes
    hist = hist_closed

    # ── 3. Dernière clôture réelle → indicateurs techniques ──
    last = hist.iloc[-1]

    # ── 4. Fondamentaux + prix temps réel via .info ───────────
    info     = stock.info
    officers = info.get("companyOfficers", [])

    # Prix live : regularMarketPrice est mis à jour en temps réel par Yahoo.
    # Fallback sur la dernière clôture historique si .info ne répond pas.
    live_price    = _safe(info.get("regularMarketPrice") or info.get("currentPrice"))
    prev_close    = _safe(info.get("regularMarketPreviousClose") or info.get("previousClose"))
    pre_market    = _safe(info.get("preMarketPrice"))
    post_market   = _safe(info.get("postMarketPrice"))

    # var_1d depuis prix live vs clôture précédente (plus précis qu'history)
    if live_price and prev_close:
        var_1d = round((live_price - prev_close) / prev_close * 100, 2)
    else:
        live_price = round(float(last["Close"]), 2)
        var_1d     = round(float(last["Ret_1d"]), 2)

    def _ind(col, default, digits=2):
        """Retourne la valeur d'un indicateur ou un défaut si NaN/absent."""
        try:
            v = float(last[col])
            return round(v, digits) if not pd.isna(v) else default
        except Exception:
            return default

    return {
        # Identification
        "ticker":         ticker.upper(),
        "company_name":   info.get("longName", ticker),
        "sector":         info.get("sector",   "N/A"),
        "industry":       info.get("industry", "N/A"),

        # Prix temps réel (depuis .info, pas history)
        "price":          round(live_price, 2),
        "prev_close":     round(prev_close, 2) if prev_close else None,
        "pre_market":     round(pre_market,  2) if pre_market  else None,
        "post_market":    round(post_market, 2) if post_market else None,
        "var_1d":         var_1d,
        "var_5d":         _ind("Ret_5d",  0.0),
        "var_30d":        _ind("Ret_30d", 0.0),

        # Indicateurs techniques (50/price/0 si historique insuffisant)
        "rsi":            _ind("RSI",      50.0, digits=1),
        "ma20":           _ind("MA20",     live_price),
        "ma50":           _ind("MA50",     live_price),
        "macd":           _ind("MACD",     0.0, digits=4),
        "macd_signal":    _ind("MACD_sig", 0.0, digits=4),
        "bb_upper":       _ind("BB_upper", round(live_price * 1.05, 2)),
        "bb_lower":       _ind("BB_lower", round(live_price * 0.95, 2)),
        "vol_ratio":      _ind("Vol_ratio", 1.0),

        # Fondamentaux
        "pe_ratio":       _safe(info.get("trailingPE")),
        "eps":            _safe(info.get("trailingEps")),
        "debt_equity":    _safe(info.get("debtToEquity")),
        "revenue_growth": _safe(info.get("revenueGrowth")),
        "market_cap":     _safe(info.get("marketCap")),
        "dividend_yield": _safe(info.get("dividendYield")),

        # Dirigeants
        "ceo_name":       _find_officer(officers, "CEO"),
        "cfo_name":       _find_officer(officers, "CFO"),
        "officers":       officers,

        # DataFrame complet (pour les graphiques)
        "history":        hist,
    }