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
from config import KEYWORD_SEVERITY_MAP, SEVERITY_PENALTY_POINTS


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


# ── Codes SEC → direction ─────────────────────────────────
_BUY_CODES  = {"P", "A", "M"}   # Purchase, Award/Grant, Exercise
_SELL_CODES = {"S", "D", "F"}   # Sale, Disposition, Forfeiture


def _finnhub_direction(code: str, change: float) -> str | None:
    c = str(code).strip().upper()
    if c in _BUY_CODES:
        return "BUY"
    if c in _SELL_CODES:
        return "SELL"
    # Fallback sur le signe du changement net
    if change > 0:
        return "BUY"
    if change < 0:
        return "SELL"
    return None


# ── Transactions insider (Finnhub primaire, yfinance fallback) ──
def get_insider_transactions(ticker: str) -> pd.DataFrame:
    import os, requests as req

    _EMPTY = pd.DataFrame(columns=["date", "nom", "titre", "direction", "titres", "valeur"])

    # ── Finnhub (primaire — fonctionne sur serveur cloud) ─
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if api_key:
        try:
            r = req.get(
                "https://finnhub.io/api/v1/stock/insider-transactions",
                params={"symbol": ticker, "token": api_key},
                timeout=8,
            )
            r.raise_for_status()
            txs = r.json().get("data", [])
            if txs:
                rows = []
                for t in txs:
                    change = float(t.get("change") or 0)
                    price  = float(t.get("transactionPrice") or 0)
                    direc  = _finnhub_direction(t.get("transactionCode", ""), change)
                    if direc is None:
                        continue
                    rows.append({
                        "date":      t.get("transactionDate", ""),
                        "nom":       t.get("name", ""),
                        "titre":     "",
                        "direction": direc,
                        "titres":    abs(change),
                        "valeur":    round(abs(change) * price, 2) if price else 0.0,
                    })
                if rows:
                    df = pd.DataFrame(rows).sort_values("date", ascending=False)
                    return df.head(15).reset_index(drop=True)
        except Exception as e:
            print(f"[Insider/Finnhub] {e}", flush=True)

    # ── Fallback yfinance (marché local / dev) ─────────────
    try:
        stock = yf.Ticker(ticker)
        df = stock.insider_transactions
        if df is None or df.empty:
            return _EMPTY
        df = _normalize_columns(df)
        df["titres"] = pd.to_numeric(df["titres"], errors="coerce").fillna(0)
        df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce").fillna(0)
        df["direction"] = df.apply(_infer_direction, axis=1)
        cols = ["date", "nom", "titre", "direction", "titres", "valeur"]
        return df[cols].head(15)
    except Exception as e:
        print(f"[Insider/yfinance] {e}", flush=True)
        return _EMPTY


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
def _fetch_rss(url: str, timeout: int = 6):
    """
    Télécharge le flux via requests AVEC timeout, puis parse le contenu.
    Pourquoi : feedparser.parse(url) fait l'appel réseau lui-même SANS
    timeout — une réponse lente de Google News gelait l'analyse entière
    (jusqu'à 2 minutes mesurées). Ici : 6 s maximum par flux.
    """
    import requests
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"})
        return feedparser.parse(r.content)
    except Exception as e:
        print(f"[Insider] RSS timeout/erreur : {e}", flush=True)
        return feedparser.parse(b"")     # flux vide → 0 entrée, pas de crash


def get_executive_events(ceo_name: str, ticker: str) -> pd.DataFrame:
    """
    Alertes RSS sur le CEO — uniquement si le mot-clé apparaît
    dans le titre ET le dirigeant est mentionné (limite les faux positifs).

    Optimisation : 3 requêtes OR groupées (une par niveau de sévérité)
    au lieu d'une requête PAR mot-clé (32 appels séquentiels avant —
    principal poste du temps d'analyse). Google News accepte la syntaxe
    `"CEO" (kw1 OR kw2 OR ...)`, et le filtre par titre ci-dessous
    garantit la même qualité : un article n'est retenu que si un
    mot-clé exact figure dans son titre.
    """
    from config import (KEYWORDS_SCANDAL_CRITICAL, KEYWORDS_SCANDAL_HIGH,
                        KEYWORDS_NEGATIVE_MED)
    groupes = [KEYWORDS_SCANDAL_CRITICAL, KEYWORDS_SCANDAL_HIGH,
               KEYWORDS_NEGATIVE_MED]

    seen_urls: set[str] = set()
    alerts = []

    for kws in groupes:
        # Les mots-clés composés doivent rester entre guillemets dans le OR
        ors   = " OR ".join(f'"{k}"' if " " in k else k for k in kws)
        query = urllib.parse.quote(f'"{ceo_name}" ({ors})')
        url   = f"https://news.google.com/rss/search?q={query}&hl=en"
        feed  = _fetch_rss(url)

        # Une requête couvre ~10 mots-clés → on lit plus d'entrées
        # (avant : 2 entrées × 32 requêtes)
        for entry in feed.entries[:15]:
            titre = entry.get("title", "")
            link  = entry.get("link", "")

            if link in seen_urls:
                continue
            if not _ceo_relevant(ceo_name, titre):
                continue
            # Quel mot-clé du groupe a réellement matché le titre ?
            kw = next((k for k in kws if _keyword_in_title(k, titre)), None)
            if kw is None:
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
