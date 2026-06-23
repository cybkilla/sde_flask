# data/insider.py — version corrigée
# Fix : mapping défensif des colonnes yfinance.
# yfinance change ses noms de colonnes selon les versions ;
# on cherche chaque colonne par plusieurs noms possibles.

import re
import yfinance   as yf
import pandas    as pd
import feedparser
import urllib.parse
import numpy     as np
from config import EXEC_KEYWORDS, KEYWORD_SEVERITY_MAP, SEVERITY_PENALTY_POINTS


# ── Mapping défensif des colonnes yfinance ────────────────
_COL_MAP = {
    "nom":       ["Insider", "Name", "filerName", "name"],
    "titre":     ["Title", "Position", "filerRelation", "title"],
    "type":      ["Transaction", "Type", "transactionType", "type"],
    "titres":    ["Shares", "shares", "sharesOwnedDirectly", "Value"],
    "valeur":    ["Value", "value", "moneyValue"],
    "date":      ["Start Date", "Date", "startDate", "date"],
    "ownership": ["Ownership", "ownership"],
    "text":      ["Text", "text", "description"],
}


def _find_col(df: pd.DataFrame, candidates: list) -> str | None:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    missing    = []

    for target, candidates in _COL_MAP.items():
        found = _find_col(df, candidates)
        if found:
            if found != target:
                rename_map[found] = target
        else:
            missing.append(target)

    df = df.rename(columns=rename_map)

    for col in missing:
        df[col] = ""

    return df


def _infer_direction(row: pd.Series) -> str | None:
    """
    Déduit BUY / SELL uniquement si le signal est explicite.
    Les lignes ambiguës (Transaction vide chez yfinance) sont ignorées.
    """
    tx   = str(row.get("type", "")).strip()
    text = str(row.get("text", "")).strip()
    own  = str(row.get("ownership", "")).strip().upper()
    blob = f"{tx} {text}".lower()

    if re.search(r"purchase|buy|achat|acquisition", blob, re.I):
        return "BUY"
    if re.search(r"sale|sell|vente|disposition|sold", blob, re.I):
        return "SELL"

    # Codes SEC fréquents dans Ownership (yfinance)
    if own in ("P",):
        return "BUY"
    if own in ("S", "D"):
        return "SELL"

    return None


def _ceo_relevant(ceo_name: str, title: str) -> bool:
    """Le dirigeant doit être mentionné dans le titre de l'article."""
    if not ceo_name or not title:
        return False
    title_l = title.lower()
    parts = [p for p in re.split(r"\s+", ceo_name.strip()) if len(p) > 2]
    if not parts:
        return True
    # Nom de famille ou prénom distinctif
    return any(p.lower() in title_l for p in parts)


def _keyword_in_title(keyword: str, title: str) -> bool:
    """Mot-clé entier dans le titre (évite les faux positifs RSS)."""
    return bool(re.search(rf"\b{re.escape(keyword)}\b", title, re.I))


# ── Transactions insider (yfinance) ───────────────────────
def get_insider_transactions(ticker: str) -> pd.DataFrame:
    stock = yf.Ticker(ticker)
    df = stock.insider_transactions

    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "date", "nom", "titre", "direction", "titres", "valeur",
        ])

    df = _normalize_columns(df)
    df["titres"] = pd.to_numeric(df["titres"], errors="coerce").fillna(0)
    df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce").fillna(0)
    df["direction"] = df.apply(_infer_direction, axis=1)

    cols = ["date", "nom", "titre", "direction", "titres", "valeur"]
    return df[cols].head(15)


# ── Score insider ─────────────────────────────────────────
def get_insider_score(df_tx: pd.DataFrame) -> dict:
    """Signal insider basé sur le volume net (achats − ventes explicites)."""
    if df_tx.empty or "direction" not in df_tx.columns:
        return {"net_signal": "NEUTRE", "achats": 0, "ventes": 0}

    known = df_tx[df_tx["direction"].isin(["BUY", "SELL"])]
    if known.empty:
        return {"net_signal": "NEUTRE", "achats": 0, "ventes": 0}

    agg    = known.groupby("direction")["titres"].sum()
    achats = int(agg.get("BUY",  0))
    ventes = int(agg.get("SELL", 0))
    net    = achats - ventes

    if net > 0:
        signal = "BUY"
    elif net < 0:
        signal = "SELL"
    else:
        signal = "NEUTRE"

    return {"net_signal": signal, "achats": achats, "ventes": ventes}


# ── Événements personnels dirigeants (RSS) ────────────────
def get_executive_events(ceo_name: str, ticker: str) -> pd.DataFrame:
    """
    Alertes RSS sur le CEO — uniquement si le mot-clé apparaît
    dans le titre ET le dirigeant est mentionné (limite les faux positifs).
    """
    seen_urls: set[str] = set()
    alerts = []

    for kw in EXEC_KEYWORDS:
        query = urllib.parse.quote(f'"{ceo_name}" {kw}')
        url   = f"https://news.google.com/rss/search?q={query}&hl=en"
        feed  = feedparser.parse(url)

        for entry in feed.entries[:2]:
            titre = entry.get("title", "")
            link  = entry.get("link", "")

            if link in seen_urls:
                continue
            if not _ceo_relevant(ceo_name, titre):
                continue
            if not _keyword_in_title(kw, titre):
                continue

            seen_urls.add(link)
            severite = KEYWORD_SEVERITY_MAP.get(kw, "MOYENNE")
            alerts.append({
                "mot_cle":  kw,
                "titre":    titre,
                "date":     entry.get("published", ""),
                "severite": severite,
                "url":      link,
            })

    df = pd.DataFrame(alerts)
    if df.empty:
        return df

    df["penalite"] = df["severite"].map(SEVERITY_PENALTY_POINTS).fillna(5).astype(int)
    # Ordre : CRITIQUE → HAUTE → MOYENNE
    sev_order = {"CRITIQUE": 0, "HAUTE": 1, "MOYENNE": 2, "POSITIVE": 3}
    df["_ord"] = df["severite"].map(sev_order).fillna(9)
    return df.sort_values("_ord").drop(columns="_ord").reset_index(drop=True)


# ── Pénalité totale ───────────────────────────────────────
def compute_exec_penalty(df_events: pd.DataFrame) -> float:
    """
    Pénalité plafonnée, une fois par article (pas par mot-clé RSS).
    Impact modéré sur le score médiatique agrégé.
    """
    if df_events.empty or "penalite" not in df_events.columns:
        return 0.0
    if "url" in df_events.columns:
        per_article = df_events.groupby("url", as_index=False)["penalite"].max()
        total = float(per_article["penalite"].sum())
    else:
        total = float(df_events["penalite"].sum())
    return float(np.clip(total, 0, 40))
