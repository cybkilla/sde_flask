# utils/ticker_search.py — recherche de tickers via Finnhub symbol_search
import pandas as pd
from config import FINNHUB_API_KEY


def search_tickers(query: str, max_results: int = 8) -> pd.DataFrame:
    """
    Recherche des tickers correspondant à un nom de société (NASDAQ / NYSE).

    Retour : pd.DataFrame avec colonnes ticker, nom, exchange, type, label.
    """
    if not query or len(query.strip()) < 2:
        return pd.DataFrame()

    try:
        import finnhub
        client  = finnhub.Client(api_key=FINNHUB_API_KEY)
        results = client.symbol_lookup(query.strip())
        items   = results.get("result", [])

        if not items:
            return pd.DataFrame()

        df = pd.DataFrame(items)
        # Colonnes Finnhub : description, displaySymbol, symbol, type
        df = df.rename(columns={"symbol": "ticker", "description": "nom"})

        # Marchés US uniquement (pas de point dans le ticker = pas de suffix d'échange)
        df = df[~df["ticker"].str.contains(r"\.", na=False)]

        # Actions et ETF uniquement
        df = df[df["type"].isin(["Common Stock", "ETP"])]

        df = df[df["ticker"].str.strip() != ""]
        df = df[df["nom"].str.strip()    != ""]

        df["exchange"] = "NASDAQ/NYSE"
        df["label"]    = df["ticker"] + " — " + df["nom"]

        return df[["ticker", "nom", "exchange", "type", "label"]].head(max_results)

    except Exception as e:
        print(f"[search_tickers] Erreur : {e}")
        return pd.DataFrame()
