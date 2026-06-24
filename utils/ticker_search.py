# utils/ticker_search.py — yfinance (primaire) → Finnhub (fallback cloud)
import pandas as pd


def search_tickers(query: str, max_results: int = 8) -> pd.DataFrame:
    """
    Recherche des tickers par nom de société.
    Essaie yfinance.Search en premier ; bascule sur Finnhub symbol_lookup
    si Yahoo Finance est inaccessible (cloud, rate limit…).

    Retour : DataFrame avec colonnes ticker, nom, exchange, type, label.
    """
    if not query or len(query.strip()) < 2:
        return pd.DataFrame()

    # ── Primaire : yfinance ──────────────────────────────
    try:
        import yfinance as yf
        results = yf.Search(query.strip(), max_results=max_results)
        quotes  = results.quotes or []

        if quotes:
            df = pd.DataFrame(quotes)

            def _col(name):
                return df[name] if name in df.columns else pd.Series(
                    [None] * len(df), index=df.index, dtype=object
                )

            df["ticker"]   = _col("symbol").fillna("").astype(str)
            df["nom"]      = _col("longname").fillna(_col("shortname")).fillna("").astype(str)
            df["exchange"] = _col("exchange").fillna("").astype(str)
            df["type"]     = _col("quoteType").fillna("").astype(str)
            df = df[df["type"].isin(["EQUITY", "ETF"])]
            df = df[df["ticker"].str.strip() != ""]
            df = df[df["nom"].str.strip()    != ""]
            df["label"] = df["ticker"] + " — " + df["nom"] + " (" + df["exchange"] + ")"
            df = df[df["label"].str.len() > 3]

            result = df[["ticker", "nom", "exchange", "type", "label"]].head(max_results)
            if not result.empty:
                return result
    except Exception as e:
        print(f"[search_tickers] yfinance indisponible ({e}) — bascule Finnhub")

    # ── Fallback : Finnhub symbol_lookup ─────────────────
    try:
        from config import FINNHUB_API_KEY
        import finnhub
        client  = finnhub.Client(api_key=FINNHUB_API_KEY)
        results = client.symbol_lookup(query.strip())
        items   = results.get("result", [])

        if not items:
            return pd.DataFrame()

        df = pd.DataFrame(items)
        df = df.rename(columns={"symbol": "ticker", "description": "nom"})
        df = df[~df["ticker"].str.contains(r"\.", na=False)]   # US uniquement
        df = df[df["type"].isin(["Common Stock", "ETP"])]
        df = df[df["ticker"].str.strip() != ""]
        df = df[df["nom"].str.strip()    != ""]
        df["exchange"] = "NASDAQ/NYSE"
        df["label"]    = df["ticker"] + " — " + df["nom"]

        return df[["ticker", "nom", "exchange", "type", "label"]].head(max_results)

    except Exception as e:
        print(f"[search_tickers] Finnhub indisponible ({e})")
        return pd.DataFrame()
