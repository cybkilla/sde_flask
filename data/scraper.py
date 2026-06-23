# data/scraper.py
# Scraping complémentaire pour enrichir les données dirigeants.
# Sources : Wikipedia (biographie CEO), OpenInsider (transactions).

import requests
import pandas  as pd
from bs4 import BeautifulSoup


# ── Wikipedia : infos biographiques du CEO ────────────────
def get_ceo_wiki_summary(ceo_name: str) -> dict:
    """
    Scrape le résumé Wikipedia d'un dirigeant.
    Utilise l'API Wikipedia (JSON) — plus fiable que le scraping HTML.
    Retourne un dict avec extrait biographique et URL.
    """
    # API Wikipedia REST — retourne JSON propre sans parsing HTML
    url    = "https://en.wikipedia.org/api/rest_v1/page/summary/"
    name   = ceo_name.replace(" ", "_")
    headers= {"User-Agent": "StockEngine/1.0"}

    try:
        resp = requests.get(url + name, headers=headers, timeout=5)
        if resp.status_code != 200:
            return {"extrait": "Non disponible", "url": ""}
        data = resp.json()
        return {
            "extrait": data.get("extract", "")[:500],  # 500 chars max
            "url":     data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "image":   data.get("thumbnail", {}).get("source", ""),
        }
    except Exception:
        return {"extrait": "Erreur de connexion", "url": ""}


# ── OpenInsider : transactions insider scrapées ────────────
def scrape_openinsider(ticker: str) -> pd.DataFrame:
    """
    Scrape le site openinsider.com pour un ticker donné.
    Retourne un DataFrame Pandas normalisé.
    Fallback si yfinance ne retourne pas de transactions.
    """
    url = f"http://openinsider.com/screener?s={ticker}&o=fd&pl=&ph=&ll=&lh=&fd=30&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=20&action=1"

    headers = {"User-Agent": "Mozilla/5.0 StockEngine/1.0"}

    try:
        resp  = requests.get(url, headers=headers, timeout=8)
        soup  = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"class": "tinytable"})

        if not table:
            return pd.DataFrame()

        # pd.read_html() parse directement le tableau HTML → DataFrame
        dfs = pd.read_html(str(table))
        if not dfs:
            return pd.DataFrame()

        df = dfs[0].copy()

        # Nettoyage Pandas vectorisé des colonnes monétaires
        for col in df.select_dtypes(include="object").columns:
            # Supprime $, virgules, + et convertit en numérique
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[\$,+]", "", regex=True),
                errors="ignore"
            )

        return df

    except Exception as e:
        print(f"[OpenInsider] Erreur : {e}")
        return pd.DataFrame()
    