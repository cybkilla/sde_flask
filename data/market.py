# data/market.py — yfinance (primaire) → Finnhub + Twelve Data (fallback cloud)
import os
import time
import concurrent.futures
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
    hist = hist.tail(45)   # indicateurs calculés sur 75j, on garde 45 lignes en mémoire
    last = hist.iloc[-1]
    _ind = _ind_fn(last, 0)

    info       = stock.info
    officers   = info.get("companyOfficers", [])
    live_price = _safe(info.get("regularMarketPrice") or info.get("currentPrice"))
    # Clôture veille depuis les bougies déjà en mémoire (`hist`), pas
    # info["regularMarketPreviousClose"] : ce champ temps-réel peut rester
    # bloqué sur l'avant-dernière séance (constaté en réel le 10.08.2026,
    # un lundi matin — encore la clôture de jeudi au lieu de vendredi).
    # Repli sur l'ancien champ si l'historique est trop court pour trancher.
    prev_close = (_cloture_avant_aujourdhui(hist)
                  or _safe(info.get("regularMarketPreviousClose") or info.get("previousClose")))
    pre_market = _safe(info.get("preMarketPrice"))
    post_market= _safe(info.get("postMarketPrice"))

    if live_price and prev_close:
        var_1d = round((live_price - prev_close) / prev_close * 100, 2)
    else:
        live_price = round(float(last["Close"]), 2)
        var_1d     = round(float(last["Ret_1d"]), 2)

    _ind = _ind_fn(last, live_price)

    # Logo via Clearbit (domaine extrait du site officiel yfinance)
    logo_url = ""
    try:
        from urllib.parse import urlparse
        website = info.get("website", "") or ""
        if website:
            domain = urlparse(website).netloc.lstrip("www.")
            if domain:
                logo_url = f"https://logo.clearbit.com/{domain}"
    except Exception:
        pass

    return {
        "ticker":         ticker,
        "logo_url":       logo_url,
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
    td = TDClient(apikey=api_key)

    def _fetch():
        return td.time_series(
            symbol=ticker, interval="1day",
            outputsize=min(days, 5000), order="ASC",
        ).as_pandas()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ts = ex.submit(_fetch).result(timeout=15)
    except concurrent.futures.TimeoutError:
        print(f"[Market] Twelve Data timeout ({ticker})", flush=True)
        return pd.DataFrame()
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
    hist = hist.tail(45)   # indicateurs calculés sur 75j, on garde 45 lignes en mémoire
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
        "logo_url":       profile.get("logo", "") or "",
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
# PRIX LIVE — appel léger Finnhub (pour rafraîchir un snapshot)
# ══════════════════════════════════════════════════════════
def _quote_finnhub(ticker: str) -> dict:
    fh    = _fh()
    quote = fh.quote(ticker.upper()) or {}
    price = _safe(quote.get("c"))
    prev  = _safe(quote.get("pc"))
    if price and prev and float(prev) > 0:
        var_1d = round((float(price) - float(prev)) / float(prev) * 100, 2)
    else:
        var_1d = 0.0
    return {
        "price":      round(float(price), 2) if price else None,
        "prev_close": round(float(prev),  2) if prev  else None,
        "var_1d":     var_1d,
    }


def _quote_yfinance(ticker: str) -> dict:
    import yfinance as yf
    fi    = yf.Ticker(ticker.upper()).fast_info
    price = getattr(fi, "last_price", None)
    prev  = getattr(fi, "previous_close", None)
    if price and prev and float(prev) > 0:
        var_1d = round((float(price) - float(prev)) / float(prev) * 100, 2)
    else:
        var_1d = 0.0
    return {
        "price":      round(float(price), 2) if price else None,
        "prev_close": round(float(prev),  2) if prev  else None,
        "var_1d":     var_1d,
    }


def get_live_price(ticker: str) -> dict:
    """
    Retourne le prix actuel et la variation du jour.
    Primaire : Finnhub /quote (léger, normalement < 1s).
    Fallback  : yfinance fast_info si Finnhub indisponible (502, timeout…).
    Retourne {} si les deux sources échouent.

    Les deux appels sont protégés par un timeout (with_timeout) — un
    /quote normalement instantané peut dégrader à plusieurs secondes
    (vécu en réel le 31.07.2026 : 12.5s sur Finnhub, aucune protection
    avant ce correctif). Même famille de risque que l'incident de
    mi-juillet qui avait rendu tout le site inaccessible
    (utils/net_timeout.py, alors appliqué aux appels yfinance seulement).
    """
    from utils.net_timeout import with_timeout

    # ── Tentative Finnhub ─────────────────────────────────
    try:
        return with_timeout(_quote_finnhub, 6, ticker)
    except Exception as e:
        print(f"[Market] Finnhub indisponible ({ticker}) : {type(e).__name__} — fallback yfinance", flush=True)

    # ── Fallback yfinance fast_info ───────────────────────
    try:
        return with_timeout(_quote_yfinance, 8, ticker)
    except Exception as e2:
        print(f"[Market] get_live_price({ticker}) tous les fallbacks ont échoué : {e2}", flush=True)
        return {}


def _cloture_avant_aujourdhui(hist) -> float | None:
    """
    Dernière clôture d'une séance ANTÉRIEURE à aujourd'hui (heure de
    marché US) — pas simplement la dernière ligne de l'historique
    (`.iloc[-1]`), qui peut être la bougie du jour EN COURS de formation
    si le marché est ouvert au moment de l'appel (yfinance ajoute une
    ligne "aujourd'hui" dès l'ouverture, mise à jour en direct — la
    prendre pour une "clôture" reviendrait à dupliquer le prix live).
    Fonction PURE, réutilisable sur un historique déjà en mémoire.

    Filtre aussi les Close NaN — Yahoo laisse parfois une clôture
    manquante sur la séance la plus récente (constaté en réel le
    18.08.2026 : TMC avait Close=NaN pour le 17.08, la veille pourtant
    déjà clôturée) ; sans ce filtre, `.iloc[-1]` prend cette ligne NaN
    et la propage jusqu'à la sérialisation JSON en aval.
    """
    if hist is None or hist.empty:
        return None
    import datetime
    try:
        import zoneinfo
        aujourdhui_et = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date()
    except Exception:
        aujourdhui_et = datetime.date.today()
    completes = hist[(hist.index.date < aujourdhui_et) & hist["Close"].notna()]
    if completes.empty:
        return None
    return round(float(completes["Close"].iloc[-1]), 4)


def _derniere_cloture_reelle(ticker: str) -> float | None:
    """
    Dernière clôture RÉELLE (bougie quotidienne complète) — PAS
    info["regularMarketPreviousClose"], qui peut rester bloqué sur
    l'avant-dernière séance. Constaté en réel le 10.08.2026, un lundi
    matin avant ouverture : `regularMarketPreviousClose` de TMC valait
    encore la clôture de JEUDI (4.12) au lieu de celle de VENDREDI
    (4.57, vérifiée via l'historique) — Yahoo n'avait pas fini de "rouler"
    son cache du week-end sur ce champ temps-réel. Les bougies
    quotidiennes n'ont pas ce problème.
    """
    import yfinance as yf
    hist = yf.Ticker(ticker.upper()).history(period="5d")
    return _cloture_avant_aujourdhui(hist)


def get_premarket_gap(ticker: str) -> dict | None:
    """
    Vrai gap pré-marché (prix pré-marché vs clôture de la veille) —
    PAS get_live_price()["var_1d"], qui reste figé sur la clôture de la
    veille hors séance : vérifié en réel le 31.07.2026 sur Finnhub, Twelve
    Data ET Alpha Vantage (offres gratuites) — les trois renvoient la
    même clôture de la veille tant que le marché n'a pas rouvert, même
    sur AAPL/NVDA/MSFT. Aucune des trois n'expose de prix pré-marché sur
    leur plan gratuit (Alpha Vantage le confirme explicitement : son
    endpoint extended_hours est "premium only").

    Seul yfinance (`.info["preMarketPrice"]`) a la vraie donnée — mais
    yfinance est bloqué au niveau réseau depuis Render (cf. net_timeout.py).

    Depuis le 07.08.2026, un RELAIS contourne ce blocage : une GitHub
    Action (scripts/premarche_relay.py) exécute yfinance depuis les IP
    GitHub pendant la fenêtre pré-marché et dépose les prix dans la table
    Supabase `premarche_quotes` — lue ICI en premier. L'appel yfinance
    direct reste en second (utile en dev local), puis None : toujours
    BEST EFFORT, jamais de fausse donnée (même convention que
    get_cash_disponible()).
    """
    # 1. Relais GitHub Actions (frais < 45 min — le cron passe toutes les 30)
    try:
        from db import find_one, is_available
        if is_available():
            row = find_one("premarche_quotes", {"ticker": ticker.upper()})
            # _safe() sur CHAQUE champ, pas seulement à l'écriture : une
            # ligne déposée avant le fix du 18.08.2026 (ou par un autre
            # chemin) peut contenir un NaN déjà stocké — constaté en réel
            # le même jour sur TMC (prix correct, gap_pct/prev_close NaN).
            prix = _safe(row.get("prix")) if row else None
            if row and prix is not None and row.get("fetched_at"):
                from datetime import datetime, timezone
                age_min = (datetime.now(timezone.utc)
                           - datetime.fromisoformat(row["fetched_at"])).total_seconds() / 60
                if age_min <= 45:
                    gap  = _safe(row.get("gap_pct"))
                    prev = _safe(row.get("prev_close"))
                    return {
                        "prix":       float(prix),
                        "gap_pct":    float(gap)  if gap  is not None else None,
                        "prev_close": float(prev) if prev is not None else None,
                    }
    except Exception as e:
        print(f"[Market] relais pré-marché illisible ({ticker}) : {e}", flush=True)

    # 2. yfinance direct (fonctionne en local, bloqué depuis Render)
    try:
        import yfinance as yf
        from utils.net_timeout import with_timeout
        info = with_timeout(lambda: yf.Ticker(ticker.upper()).info, 8)
        # _safe() (pas un simple .get()) : yfinance renvoie parfois NaN
        # (pas None/absent) pour preMarketPrice — pd.isna() l'attrape,
        # un "is None" ne l'aurait pas fait. NaN est en plus truthy en
        # Python ("if prev" l'aurait laissé filer jusqu'à la division),
        # et Supabase (JSON strict) rejette NaN à l'écriture — constaté
        # en réel le 18.08.2026 côté relais (même fonction dupliquée).
        pm_price = _safe(info.get("preMarketPrice")) if info else None
        pm_pct   = _safe(info.get("preMarketChangePercent")) if info else None
        if pm_price is None:
            return None
        prev = with_timeout(lambda: _derniere_cloture_reelle(ticker), 8)
        if prev is None and pm_pct is None:
            return None
        # Gap CALCULÉ depuis les deux prix qu'on affiche, pas repris du
        # champ preMarketChangePercent de Yahoo : constaté incohérent sur
        # le digest du 07.08.2026 (ITG affiché +1.9% alors que
        # 12.93→13.59 = +5.1% — les champs du .info ne sont pas
        # synchronisés entre eux). Le % Yahoo ne sert plus que de secours
        # quand la clôture veille manque.
        gap = (round((float(pm_price) / float(prev) - 1) * 100, 2) if prev is not None
               else round(float(pm_pct), 2))
        return {
            "prix":       round(float(pm_price), 4),
            "gap_pct":    gap,
            "prev_close": round(float(prev), 4) if prev is not None else None,
        }
    except Exception as e:
        print(f"[Market] get_premarket_gap({ticker}) indisponible : {e}", flush=True)
        return None


def _formater_earnings(row: dict, today) -> dict:
    """
    Met en forme UNE ligne earnings_calendar Finnhub. `epsActual` s'y
    remplit tout seul une fois les résultats publiés (pas besoin d'un
    second appel `company_earnings`) — d'où les deux statuts :
      "a_venir" : jours > 0, ou résultat pas encore publié
      "publie"  : jours <= 0 ET epsActual connu — inclut estimate/actual/
                  surprise_pct (recalculé nous-mêmes, Finnhub ne le donne
                  pas sur ce endpoint ; vérifié en réel le 14.08.2026
                  contre company_earnings : même formule, mêmes chiffres)
    """
    import datetime
    d     = datetime.datetime.strptime(row["date"], "%Y-%m-%d").date()
    jours = (d - today).days
    eps_est = row.get("epsEstimate")
    eps_act = row.get("epsActual")
    if jours <= 0 and eps_act is not None:
        surprise_pct = (round((eps_act - eps_est) / abs(eps_est) * 100, 1)
                        if eps_est else None)
        return {"date": row["date"], "jours": jours, "statut": "publie",
                "eps_estimate": eps_est, "eps_actual": eps_act,
                "surprise_pct": surprise_pct}
    return {"date": row["date"], "jours": jours, "statut": "a_venir"}


def get_next_earnings(ticker: str, horizon_jours: int = 10, retro_jours: int = 3) -> dict | None:
    """
    Résultats trimestriels : soit À VENIR (`statut` "a_venir", `jours` > 0),
    soit RÉCEMMENT PUBLIÉS (`statut` "publie", `jours` <= 0, avec le
    résultat réel vs attendu) — Finnhub `earnings_calendar`, disponible
    sur le plan gratuit (vérifié en réel le 03.08.2026, filtré par
    `symbol`, un seul appel par ticker).

    But : un choc résultats est un événement à variance élevée qu'aucun
    signal technique/fondamental ne peut anticiper — avant coup (cas réel
    MXL, ACHETER à score 65.5 suivi d'un -21.2% le lendemain) ET après
    coup, où un gros écart estimé/réel explique un mouvement de cours
    qui semblerait autrement incompréhensible (cas réel TMC 14.08.2026 :
    -8% le lendemain d'un BPA -0.14$ vs -0.06$ attendu). Best effort —
    None si indisponible ou aucune date connue, jamais bloquant.
    """
    try:
        import datetime
        from utils.net_timeout import with_timeout
        fh    = _fh()
        today = datetime.date.today()
        result = with_timeout(
            lambda: fh.earnings_calendar(
                _from=str(today - datetime.timedelta(days=retro_jours)),
                to=str(today + datetime.timedelta(days=horizon_jours)),
                symbol=ticker.upper()),
            6,
        )
        rows = (result or {}).get("earningsCalendar") or []
        if not rows:
            return None
        prochaine = min(rows, key=lambda r: r["date"])
        return _formater_earnings(prochaine, today)
    except Exception as e:
        print(f"[Market] get_next_earnings({ticker}) indisponible : {e}", flush=True)
        return None


def get_next_earnings_bulk(tickers: list[str], horizon_jours: int = 10, retro_jours: int = 3) -> dict:
    """
    Comme get_next_earnings(), mais pour plusieurs tickers en UN SEUL appel
    Finnhub (sans filtre `symbol` — le calendrier renvoie ~1500 lignes
    tous titres confondus, filtrées ici en Python) — évite le N+1 sur
    /portfolio/overview, appelée à chaque visite de la page (même souci
    de perf déjà rencontré avec les prix live et les stats de fiabilité).
    Retourne {ticker: {...}} (même forme que get_next_earnings) — absent
    si rien sous l'horizon [aujourd'hui-retro_jours ; aujourd'hui+horizon_jours].
    """
    try:
        import datetime
        from utils.net_timeout import with_timeout
        if not tickers:
            return {}
        fh    = _fh()
        today = datetime.date.today()
        result = with_timeout(
            lambda: fh.earnings_calendar(
                _from=str(today - datetime.timedelta(days=retro_jours)),
                to=str(today + datetime.timedelta(days=horizon_jours)),
                symbol=""),
            8,
        )
        rows = (result or {}).get("earningsCalendar") or []
        symboles = {t.upper() for t in tickers}
        par_ticker: dict[str, dict] = {}
        for r in rows:
            sym = r.get("symbol")
            if sym not in symboles:
                continue
            existant = par_ticker.get(sym)
            if existant is None or r["date"] < existant["date"]:
                par_ticker[sym] = r
        return {sym: _formater_earnings(r, today) for sym, r in par_ticker.items()}
    except Exception as e:
        print(f"[Market] get_next_earnings_bulk indisponible : {e}", flush=True)
        return {}


# ══════════════════════════════════════════════════════════
# POINT D'ENTRÉE — essaie yfinance, bascule sur Finnhub+TD
# ══════════════════════════════════════════════════════════
def get_market_data(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    try:
        from utils.net_timeout import with_timeout
        return with_timeout(_get_yfinance, 20, ticker)
    except Exception as e:
        print(f"[Market] yfinance indisponible pour {ticker} ({e}) — bascule Finnhub+TwelveData", flush=True)
    try:
        return _get_finnhub_fallback(ticker)
    except Exception as e2:
        print(f"[Market] {ticker} introuvable sur toutes les sources : {e2}", flush=True)
        raise ValueError(
            f"Ticker « {ticker} » introuvable sur nos sources de données. "
            f"Vérifiez le symbole ou ajoutez le suffixe du marché "
            f"(ex : AIR.PA pour Euronext, DND.TO pour TSX, VOD.L pour London)."
        )
