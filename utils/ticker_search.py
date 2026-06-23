# utils/ticker_search.py
# Recherche de tickers par nom de société via yfinance.
# Utilise yfinance.Search() qui interroge l'API Yahoo Finance
# et retourne les résultats sous forme de pd.DataFrame.

import pandas as pd
import yfinance as yf


def search_tickers(query: str, max_results: int = 8) -> pd.DataFrame:
    """
    Recherche des tickers correspondant à un nom de société.

    Paramètres
    ----------
    query       : nom ou fragment de nom (ex. "Apple", "LVMH", "Tesla")
    max_results : nombre maximum de résultats retournés

    Retour
    ------
    pd.DataFrame avec colonnes :
      ticker   : symbole boursier (ex. "AAPL")
      nom      : nom complet de la société
      exchange : bourse de cotation (NYSE, NASDAQ, EPA…)
      type     : type d'instrument (EQUITY, ETF…)
      label    : texte affiché dans la liste de suggestions
    """
    if not query or len(query.strip()) < 2:
        return pd.DataFrame()

    try:
        # yfinance.Search interroge l'API Yahoo Finance Search
        results = yf.Search(query, max_results=max_results)
        quotes  = results.quotes   # liste de dicts retournée par Yahoo

        if not quotes:
            return pd.DataFrame()

        # Conversion en DataFrame Pandas pour manipulation facile
        df = pd.DataFrame(quotes)

        # Colonnes disponibles selon les versions de yfinance :
        # symbol, shortname, longname, exchange, quoteType…
        # On extrait uniquement ce dont on a besoin
        def _col(name: str) -> pd.Series:
            """Retourne la colonne si elle existe, sinon une Series de NaN indexée.
            NaN est requis pour que .fillna() puisse faire le fallback."""
            return df[name] if name in df.columns else pd.Series(
                [None] * len(df), index=df.index, dtype=object
            )

        df["ticker"]   = _col("symbol").fillna("").astype(str)
        df["nom"]      = _col("longname").fillna(_col("shortname")).fillna("").astype(str)
        df["exchange"] = _col("exchange").fillna("").astype(str)
        df["type"]     = _col("quoteType").fillna("").astype(str)

        # Filtre : actions (EQUITY) et ETF uniquement
        df = df[df["type"].isin(["EQUITY", "ETF"])]

        # Exclure les lignes sans ticker ni nom (évite les NaN dans le label)
        df = df[df["ticker"].str.strip() != ""]
        df = df[df["nom"].str.strip() != ""]

        # Colonne label = texte affiché dans st.selectbox
        df["label"] = (
            df["ticker"] + " — " +
            df["nom"]    + " (" +
            df["exchange"] + ")"
        ).fillna("").astype(str)

        # Sécurité finale : exclure tout label vide ou NaN
        df = df[df["label"].str.len() > 3]

        return df[["ticker", "nom", "exchange", "type", "label"]].head(max_results)

    except Exception as e:
        # En cas d'erreur réseau ou API, retourne un DataFrame vide
        # sans planter l'application
        print(f"[search_tickers] Erreur : {e}")
        return pd.DataFrame()
    