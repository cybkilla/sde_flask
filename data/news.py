# data/news.py
# Collecte des actualités depuis trois sources :
#   1. Yahoo Finance News via yfinance.Ticker.news (articles directs, précis)
#   2. Google News RSS (gratuit, sans clé API)
#   3. NewsAPI (clé gratuite sur newsapi.org)
# Retourne un pd.DataFrame normalisé avec les articles.

import re
import feedparser
import urllib.parse
import pandas    as pd
import yfinance  as yf
from newsapi import NewsApiClient
from config  import NEWS_API_KEY, MAX_NEWS, MAX_SECTOR_NEWS


# ── Listes de filtrage ────────────────────────────────────
# Domaines et sources clairement non-financiers → toujours rejetés
_BLOCKED_DOMAINS = {
    "tmc.fr", "tf1.fr", "m6.fr", "france.tv", "france2.fr",
    "france3.fr", "france5.fr", "arte.tv", "canalplus.com",
    "allocine.fr", "premiere.fr", "puremedias.com", "telerama.fr",
    "programme-tv.net", "tvmag.com", "melty.fr", "voici.fr",
    "gala.fr", "closer.fr", "public.fr",
}
_BLOCKED_SOURCE_NAMES = {
    "TMC", "TF1", "M6", "France 2", "France 3", "France 5",
    "Arte", "Canal+", "Allociné", "Télé Loisirs",
}

# Domaines financiers de confiance → toujours conservés
_FINANCIAL_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "marketwatch.com", "seekingalpha.com", "investing.com",
    "yahoo.com", "finance.yahoo.com",
    "boursorama.com", "lesechos.fr", "latribune.fr",
    "bfmbusiness.com", "zonebourse.com", "boursier.com",
    "tradingsat.com", "abcbourse.com", "capital.fr",
    "challenges.fr", "businessinsider.fr", "moneyvox.fr",
    "lefigaro.fr", "lemonde.fr",
    # Sources anglo-saxonnes fréquentes dans Yahoo Finance News
    "fool.com", "zacks.com", "insidermonkey.com",
    "stocktwits.com", "thestreet.com", "investopedia.com",
    "barrons.com", "cnbc.com", "benzinga.com", "finviz.com",
    "motleyfool.com", "nasdaq.com", "businesswire.com",
    "prnewswire.com", "globenewswire.com", "accessnewswire.com",
}
# Fragments de noms de sources financières (substring, lowercase)
_FINANCIAL_SOURCE_FRAGMENTS = (
    "reuters", "bloomberg", "bourse", "finance", "invest",
    "trading", "echos", "figaro", "bfm business", "boursorama",
    "capital", "challenges", "latribune", "cnbc", "morningstar",
    "seeking alpha", "marché", "boursier", "zonebourse",
)


def _extract_domain(url: str) -> str:
    """Extrait le domaine d'une URL en retirant le www. éventuel."""
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _relevance_keywords(ticker: str, company: str) -> set:
    """
    Construit les mots-clés de pertinence depuis le ticker et le nom
    de société, utilisés en dernier recours pour les sources inconnues.
    """
    stopwords = {
        "the", "le", "la", "les", "de", "des", "du", "un", "une",
        "and", "et", "of", "for", "in", "inc", "corp", "ltd", "sa",
        "sas", "group", "groupe", "plc", "company", "co", "holding",
        "holdings", "international", "technologies", "technology",
    }
    words = {ticker.lower()}
    for w in company.lower().split():
        clean = re.sub(r"[^\w]", "", w)
        if len(clean) > 3 and clean not in stopwords:
            words.add(clean)
    return words


def _is_relevant(titre: str, resume: str, url: str,
                 source: str, keywords: set, ticker: str = "") -> bool:
    """
    Filtre multi-couche :
      1. Domaine blacklisté → rejeté
      2. Nom de source blacklisté → rejeté
      3. Domaine whitelisté (financier connu) → conservé
      4. Nom de source financier → conservé
      5. Source inconnue → filtre par mots-clés
    """
    domain     = _extract_domain(url)
    source_str = str(source).strip()

    # 1 — Blacklist domaine
    if domain and any(domain == d or domain.endswith("." + d)
                      for d in _BLOCKED_DOMAINS):
        return False

    # 2 — Blacklist nom de source (exact)
    if source_str in _BLOCKED_SOURCE_NAMES:
        return False

    # 3 — Whitelist domaine financier
    if domain and any(domain == d or domain.endswith("." + d)
                      for d in _FINANCIAL_DOMAINS):
        return True

    # 4 — Nom de source financier (fragment)
    src_lower = source_str.lower()
    if any(f in src_lower for f in _FINANCIAL_SOURCE_FRAGMENTS):
        return True

    # 5 — Source inconnue : filtre strict → ticker ET un mot-clé financier
    text = (str(titre) + " " + str(resume)).lower()
    fin_terms = {
        "stock", "share", "shares", "earnings", "revenue", "market",
        "investor", "nasdaq", "nyse", "bourse", "action", "cours",
        "analyst", "valuation", "portfolio", "dividend", "ipo",
        "quarter", "guidance", "profit", "loss", "trading",
    }
    ticker_present = ticker.lower() in text
    financial      = any(ft in text for ft in fin_terms)
    return ticker_present and financial


# ── Source 1 : Google News RSS ────────────────────────────
def _fetch_rss(query: str, max_results: int = MAX_NEWS,
               lang: str = "en") -> pd.DataFrame:
    """
    Scrape Google News RSS pour une requête donnée.
    lang="en" pour les requêtes sectorielles (en anglais),
    lang="fr" pour les requêtes entreprises francophones.
    """
    q_enc  = urllib.parse.quote(query)
    locale = "fr&gl=FR&ceid=FR:fr" if lang == "fr" else "en&gl=US&ceid=US:en"
    url    = f"https://news.google.com/rss/search?q={q_enc}&hl={locale}"

    feed     = feedparser.parse(url)
    articles = []

    for entry in feed.entries[:max_results]:
        articles.append({
            "titre":   entry.get("title",   ""),
            "resume":  entry.get("summary", ""),
            "source":  entry.get("source",  {}).get("title", "RSS"),
            "date":    entry.get("published", ""),
            "url":     entry.get("link",     ""),
            "origine": "google_rss",
        })

    return pd.DataFrame(articles)


# ── Source 2 : NewsAPI ─────────────────────────────────────
def _fetch_newsapi(company: str, ticker: str) -> pd.DataFrame:
    """
    Appelle NewsAPI pour récupérer les articles récents.
    Requiert une clé gratuite sur newsapi.org (100 req/jour).
    """
    if not NEWS_API_KEY or NEWS_API_KEY == "votre_cle_newsapi":
        return pd.DataFrame()

    try:
        api     = NewsApiClient(api_key=NEWS_API_KEY)
        results = api.get_everything(
            q=f'("{company}" OR "{ticker}") AND (stock OR shares OR finance OR earnings)',
            sort_by="publishedAt",
            page_size=MAX_NEWS,
        )
        articles = results.get("articles", [])

        df = pd.json_normalize(articles)
        df = df.rename(columns={
            "title":        "titre",
            "description":  "resume",
            "source.name":  "source",
            "publishedAt":  "date",
            "url":          "url",
        })
        df["origine"] = "newsapi"

        return df[["titre", "resume", "source", "date", "url", "origine"]]

    except Exception as e:
        print(f"[NewsAPI] Erreur : {e}")
        return pd.DataFrame()


# ── Source 3 : Yahoo Finance News (yfinance) ──────────────
def _fetch_yfinance_news(ticker: str, max_results: int = MAX_NEWS) -> pd.DataFrame:
    """
    Récupère les articles Yahoo Finance via yfinance.Ticker.news.
    Source directe : ce sont exactement les articles affichés sur
    finance.yahoo.com/quote/<ticker>/ — déjà filtrés par ticker,
    pas besoin de filtre de pertinence supplémentaire.
    """
    try:
        items = yf.Ticker(ticker).news or []
        articles = []

        for item in items[:max_results]:
            content = item.get("content") or {}

            # Ignorer les non-articles (vidéos, etc.)
            if content.get("contentType") not in ("STORY", None, ""):
                continue

            canonical = content.get("canonicalUrl")  or {}
            click     = content.get("clickThroughUrl") or {}
            url = canonical.get("url") or click.get("url") or ""

            provider = content.get("provider") or {}
            source   = (
                provider.get("displayName")
                or provider.get("sourceId")
                or "Yahoo Finance"
            )

            articles.append({
                "titre":   str(content.get("title",   "") or "").strip(),
                "resume":  str(content.get("summary") or content.get("description") or "").strip(),
                "source":  source,
                "date":    content.get("pubDate") or content.get("displayTime") or "",
                "url":     url,
                "origine": "yfinance",
            })

        return pd.DataFrame(articles)

    except Exception as e:
        print(f"[YFinanceNews] Erreur : {e}")
        return pd.DataFrame()


# ── Fonction principale : agrégation des trois sources ────
def get_all_news(company: str, ticker: str) -> pd.DataFrame:
    """
    Combine Google News RSS + NewsAPI en un seul DataFrame.
    Applique un filtre multi-couche pour exclure les articles
    hors-sujet (homonymes, médias non-financiers).

    Retour
    ------
    pd.DataFrame avec colonnes :
      titre | resume | source | date | url | origine | texte_full
    """
    # Source 1 : Yahoo Finance News — directe et ticker-spécifique
    df_yf = _fetch_yfinance_news(ticker, max_results=MAX_NEWS)

    # Source 2 : Google News RSS — cherche en anglais ET en français
    rss_query = f'"{company}" OR "{ticker}" stock finance'
    df_rss    = _fetch_rss(rss_query, max_results=MAX_NEWS)

    # Source 3 : NewsAPI
    df_api = _fetch_newsapi(company, ticker)

    # ── Assemblage ────────────────────────────────────────
    # Les articles yfinance sont déjà ticker-spécifiques → pas de filtre
    # RSS + NewsAPI passent par le filtre de pertinence

    df_indirect = pd.concat([df_rss, df_api], ignore_index=True)

    if not df_indirect.empty:
        df_indirect["titre"]  = df_indirect["titre"].fillna("").str.strip()
        df_indirect["resume"] = df_indirect["resume"].fillna("").str.strip()
        df_indirect["url"]    = df_indirect["url"].fillna("")
        df_indirect["source"] = df_indirect["source"].fillna("RSS")
        df_indirect["resume"] = df_indirect["resume"].str.replace(
            r"<[^>]+>", "", regex=True
        )
        df_indirect = df_indirect.drop_duplicates(subset="titre", keep="first")

        keywords = _relevance_keywords(ticker, company)
        mask = df_indirect.apply(
            lambda r: _is_relevant(
                r["titre"], r["resume"], r["url"], r["source"], keywords, ticker
            ),
            axis=1,
        )
        df_indirect = df_indirect[mask]

    # Fusion : yfinance en premier (plus récents et pertinents)
    df = pd.concat([df_yf, df_indirect], ignore_index=True)

    if df.empty:
        return df

    # Nettoyage final et déduplication globale
    df["titre"]  = df["titre"].fillna("").str.strip()
    df["resume"] = df["resume"].fillna("").str.strip()
    df["url"]    = df["url"].fillna("")
    df["source"] = df["source"].fillna("Yahoo Finance")
    df["resume"] = df["resume"].str.replace(r"<[^>]+>", "", regex=True)
    df = df.drop_duplicates(subset="titre", keep="first")

    # Texte complet pour le modèle NLP (limité à 512 chars)
    df["texte_full"] = (df["titre"] + ". " + df["resume"]).str[:512]

    return df.reset_index(drop=True)


# ── Mapping secteur large → requête RSS (fallback) ────────
_SECTOR_QUERIES: dict[str, str] = {
    "Technology":             "technology stocks semiconductors AI software earnings",
    "Energy":                 "energy stocks oil gas renewable earnings",
    "Basic Materials":        "mining metals materials commodities stocks",
    "Healthcare":             "healthcare biotech pharma FDA stocks earnings",
    "Financial Services":     "banking finance interest rates stocks earnings",
    "Financials":             "banking finance interest rates stocks earnings",
    "Consumer Cyclical":      "consumer discretionary retail auto stocks",
    "Consumer Defensive":     "consumer staples food beverage stocks earnings",
    "Industrials":            "industrial stocks aerospace defense infrastructure",
    "Real Estate":            "real estate REIT property stocks",
    "Utilities":              "utilities electricity water gas stocks",
    "Communication Services": "telecom media streaming stocks earnings",
}

# ── Mapping industrie précise → requête RSS ────────────────
# Prioritaire sur _SECTOR_QUERIES — correspond au champ yfinance "industry"
_INDUSTRY_QUERIES: dict[str, str] = {
    # Basic Materials
    "Other Industrial Metals & Mining": "deep sea mining critical minerals battery metals stocks",
    "Gold":                             "gold mining stocks price bullion GDX",
    "Copper":                           "copper mining stocks price supply demand",
    "Steel":                            "steel stocks iron ore production tariffs",
    "Specialty Chemicals":              "specialty chemicals stocks earnings demand",
    "Agricultural Inputs":              "fertilizers potash nitrogen crop nutrients stocks",
    "Aluminum":                         "aluminum stocks bauxite smelting LME price",
    "Coal":                             "coal stocks mining production price",
    "Silver":                           "silver mining stocks precious metals price",

    # Technology
    "Semiconductors":                   "semiconductor stocks chips AI NVIDIA AMD TSMC",
    "Consumer Electronics":             "consumer electronics Apple Samsung devices stocks",
    "Software - Infrastructure":        "cloud software cybersecurity stocks SaaS earnings",
    "Software - Application":           "SaaS enterprise software stocks earnings ARR",
    "Information Technology Services":  "IT services outsourcing cloud stocks earnings",
    "Internet Content & Information":   "internet digital advertising stocks Google Meta",
    "Electronic Components":            "electronic components supply chain stocks",
    "Computer Hardware":                "computer hardware server stocks earnings",

    # Energy
    "Oil & Gas Integrated":             "oil gas majors stocks OPEC price integrated",
    "Oil & Gas E&P":                    "oil gas exploration production stocks drilling",
    "Oil & Gas Equipment & Services":   "oilfield services stocks Schlumberger Halliburton",
    "Solar":                            "solar energy stocks panels IRA subsidies",
    "Renewable Utilities":              "renewable energy wind solar stocks power",
    "Utilities - Regulated Electric":   "regulated electric utility stocks dividend rate",

    # Financial Services
    "Banks - Diversified":              "bank stocks interest rates Fed earnings loans",
    "Banks - Regional":                 "regional bank stocks interest rates deposits",
    "Asset Management":                 "asset management stocks AUM fees ETF flows",
    "Insurance - Property & Casualty":  "P&C insurance stocks catastrophe losses premiums",
    "Insurance - Life":                 "life insurance stocks premiums earnings",
    "Credit Services":                  "credit card payments stocks Visa Mastercard",
    "Capital Markets":                  "investment banking capital markets stocks IPO M&A",

    # Consumer Cyclical
    "Luxury Goods":                     "luxury goods stocks LVMH Hermes consumer spending",
    "Auto Manufacturers":               "auto stocks EV electric vehicles production",
    "Retail - Specialty":               "specialty retail stocks same-store sales earnings",
    "Restaurants":                      "restaurant chain stocks same-store sales traffic",
    "Travel Services":                  "travel tourism hotel airline stocks demand",
    "Apparel Retail":                   "apparel retail stocks fashion inventory earnings",

    # Healthcare
    "Biotechnology":                    "biotech stocks FDA approval clinical trials pipeline",
    "Drug Manufacturers - General":     "pharma stocks drug pricing FDA approval",
    "Drug Manufacturers - Specialty":   "specialty pharma stocks rare disease drugs",
    "Medical Devices":                  "medical devices stocks FDA clearance innovation",
    "Health Information Services":      "healthcare IT stocks EHR digital health",
    "Diagnostics & Research":           "diagnostics CRO biotech research stocks",

    # Industrials
    "Aerospace & Defense":              "aerospace defense stocks contracts budget spending",
    "Airlines":                         "airline stocks capacity fuel costs travel demand",
    "Railroads":                        "railroad stocks freight volume pricing",
    "Industrial Conglomerates":         "industrial conglomerate stocks earnings segments",
    "Waste Management":                 "waste management recycling stocks contracts",
    "Engineering & Construction":       "construction engineering infrastructure stocks",

    # Communication Services
    "Telecom Services":                 "telecom stocks 5G subscribers ARPU earnings",
    "Entertainment":                    "entertainment streaming studios stocks subscribers",
    "Internet Content & Information":   "digital media advertising social media stocks",

    # Real Estate
    "REIT - Diversified":               "diversified REIT stocks dividend NAV occupancy",
    "REIT - Office":                    "office REIT stocks vacancy remote work",
    "REIT - Retail":                    "retail REIT stocks mall occupancy e-commerce",
    "REIT - Residential":               "residential REIT stocks rents occupancy housing",
}


def get_sector_news(sector: str, industry: str = "") -> pd.DataFrame:
    """
    Récupère les actualités liées au SECTEUR/INDUSTRIE du ticker.

    Priorité : industrie précise (ex. "Other Industrial Metals & Mining")
               > secteur large (ex. "Basic Materials")
    Ainsi les news sectorielles sont vraiment pertinentes pour le ticker.

    Retourne un DataFrame avec les mêmes colonnes que get_all_news(),
    plus une colonne 'type' = "secteur".
    """
    if not sector or sector in ("N/A", "Unknown", ""):
        return pd.DataFrame()

    # Industrie précise en priorité, secteur large en fallback
    query = (
        _INDUSTRY_QUERIES.get(industry)
        or _SECTOR_QUERIES.get(sector)
        or f"{industry or sector} stocks market"
    )
    df = _fetch_rss(query, max_results=MAX_SECTOR_NEWS, lang="en")

    if df.empty:
        return df

    df["titre"]  = df["titre"].fillna("").str.strip()
    df["resume"] = df["resume"].fillna("").str.strip()
    df["url"]    = df["url"].fillna("")
    df["source"] = df["source"].fillna("RSS")
    df["resume"] = df["resume"].str.replace(r"<[^>]+>", "", regex=True)
    df = df.drop_duplicates(subset="titre", keep="first")

    # Conserver uniquement les articles de sources financières reconnues
    mask = df.apply(
        lambda r: not (
            _extract_domain(r["url"]) and
            any(_extract_domain(r["url"]) == d or
                _extract_domain(r["url"]).endswith("." + d)
                for d in _BLOCKED_DOMAINS)
        ),
        axis=1,
    )
    df = df[mask]

    if df.empty:
        return df

    df["texte_full"] = (df["titre"] + ". " + df["resume"]).str[:512]
    df["type"] = "secteur"

    return df.reset_index(drop=True)
