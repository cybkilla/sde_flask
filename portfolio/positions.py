# portfolio/positions.py — CRUD positions boursières
# Supabase (si dispo) ou fallback JSON local.

import json
from datetime import date
from pathlib  import Path

_LOCAL_FILE = Path(__file__).parent / "positions_local.json"


def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def _jload() -> list:
    if _LOCAL_FILE.exists():
        return json.loads(_LOCAL_FILE.read_text())
    return []


def _jsave(data: list):
    _LOCAL_FILE.write_text(json.dumps(data, indent=2, default=str))


# ── Lecture ───────────────────────────────────────────────────────────────────

def get_positions(username: str, ticker: str = None) -> list:
    """Retourne les lots d'achat d'un utilisateur, optionnellement filtrés par ticker."""
    if _db_ok():
        try:
            from db import _init, _client
            _init()
            q = _client.table("positions").select("*").eq("username", username)
            if ticker:
                q = q.eq("ticker", ticker.upper())
            rows = q.order("date_achat").execute().data or []
            return rows
        except Exception as e:
            print(f"[Portfolio] get_positions erreur : {e}", flush=True)
    # Fallback local
    rows = _jload()
    rows = [r for r in rows if r["username"] == username]
    if ticker:
        rows = [r for r in rows if r["ticker"] == ticker.upper()]
    return sorted(rows, key=lambda r: r.get("date_achat", ""))


def get_portfolio_summary(username: str, ticker: str, current_price: float) -> dict | None:
    """
    Agrège tous les lots d'un ticker et calcule la P&L nette (achats - ventes).
    Retourne None si aucun achat.
    """
    lots = get_positions(username, ticker)
    if not lots:
        return None

    buy_lots  = [l for l in lots if l.get("type", "achat") in ("achat", "import")]
    sell_lots = [l for l in lots if l.get("type") == "vente"]

    if not buy_lots:
        return None

    total_buy_shares  = sum(float(l["quantite"]) for l in buy_lots)
    total_sell_shares = sum(float(l["quantite"]) for l in sell_lots)
    total_shares      = total_buy_shares - total_sell_shares

    total_buy_amount  = sum(float(l["quantite"]) * float(l["prix_achat"]) for l in buy_lots)
    cout_moyen        = total_buy_amount / total_buy_shares

    # P&L réalisé sur les actions déjà vendues
    total_sell_amount = sum(float(l["quantite"]) * float(l["prix_achat"]) for l in sell_lots)
    pnl_realise       = total_sell_amount - (total_sell_shares * cout_moyen)

    # P&L non réalisé sur les actions encore en portefeuille
    valeur_actuelle   = total_shares * (current_price or 0)
    pnl_non_realise   = total_shares * ((current_price or 0) - cout_moyen) if total_shares > 0 else 0

    # P&L total = réalisé + non réalisé
    pnl_total         = pnl_realise + pnl_non_realise
    base_cout_total   = total_buy_amount  # coût total de tous les achats
    pnl_pct           = (pnl_total / base_cout_total * 100) if base_cout_total > 0 else 0

    position_fermee   = total_shares <= 0

    return {
        "lots":              lots,
        "total_shares":      round(total_shares,      4),
        "cout_moyen":        round(cout_moyen,         4),
        "total_investi":     round(base_cout_total,    2),
        "valeur_actuelle":   round(valeur_actuelle,    2),
        "pnl_realise":       round(pnl_realise,        2),
        "pnl_non_realise":   round(pnl_non_realise,    2),
        "pnl_euros":         round(pnl_total,          2),
        "pnl_pct":           round(pnl_pct,            2),
        "currency":          lots[0].get("currency", "USD"),
        "position_fermee":   position_fermee,
    }


# ── Écriture ──────────────────────────────────────────────────────────────────

def add_position(username: str, ticker: str, company: str,
                 date_achat: str, prix_achat: float,
                 quantite: float, currency: str = "USD", notes: str = "",
                 type_op: str = "achat", conseil_date: str = None) -> dict:
    """Insère un lot d'achat ou de vente. Retourne la ligne créée."""
    ticker = ticker.upper()
    row = {
        "username":     username,
        "ticker":       ticker,
        "company":      company,
        "date_achat":   str(date_achat),
        "prix_achat":   float(prix_achat),
        "quantite":     float(quantite),
        "currency":     currency,
        "notes":        notes,
        "type":         type_op if type_op in ("achat", "vente", "import") else "achat",
        "conseil_date": conseil_date or None,
    }
    if _db_ok():
        try:
            from db import _init, _client
            _init()
            result = _client.table("positions").insert(row).execute()
            return result.data[0] if result.data else row
        except Exception as e:
            print(f"[Portfolio] add_position erreur : {e}", flush=True)
    # Fallback local
    data = _jload()
    row["id"] = max((r.get("id", 0) for r in data), default=0) + 1
    data.append(row)
    _jsave(data)
    return row


def delete_position(position_id: int, username: str) -> bool:
    """Supprime un lot. Vérifie que le lot appartient bien à username."""
    if _db_ok():
        try:
            from db import _init, _client
            _init()
            _client.table("positions").delete()\
                .eq("id", position_id).eq("username", username).execute()
            return True
        except Exception as e:
            print(f"[Portfolio] delete_position erreur : {e}", flush=True)
    # Fallback local
    data  = _jload()
    avant = len(data)
    data  = [r for r in data if not (r.get("id") == position_id and r["username"] == username)]
    _jsave(data)
    return len(data) < avant


def get_cash_disponible(username: str):
    """
    Trésorerie SUIVIE de l'utilisateur, tous tickers confondus :
    somme des ventes enregistrées − somme des achats enregistrés.

    Les lots 'import' sont exclus : ils représentent des titres acquis
    AVANT le suivi SDE, payés avec de l'argent que l'app n'a jamais vu.

    Retourne None si le solde est négatif : cela signifie que des achats
    ont été financés par du cash externe non tracké — on ne peut alors
    RIEN affirmer sur la trésorerie réelle, et l'appelant ne doit pas
    contraindre les conseils (mieux vaut pas d'info qu'une info fausse).
    """
    try:
        lots = get_positions(username)
        achats = sum(float(l["quantite"]) * float(l["prix_achat"])
                     for l in lots if l.get("type", "achat") == "achat")
        ventes = sum(float(l["quantite"]) * float(l["prix_achat"])
                     for l in lots if l.get("type") == "vente")
        solde = round(ventes - achats, 2)
        return solde if solde >= 0 else None
    except Exception as e:
        print(f"[Portfolio] get_cash_disponible erreur : {e}", flush=True)
        return None


def etat_compte(lots: list, prix_par_ticker: dict) -> dict:
    """
    Photographie du compte à partir des lots (UNE devise) et des prix
    actuels. Fonction PURE — source de vérité unique pour le rapport
    hebdo, l'en-tête de page et les comparaisons.

    Retourne :
      valeur_positions : Σ actions détenues × prix actuel
      cash             : Σventes − Σachats (convention : 'achat' financé
                         par le cash suivi, 'import' = cash externe exclu),
                         plancher 0
      total            : valeur_positions + cash — LA métrique objectif
      buy_hold         : valeur qu'aurait le compte si on n'avait JAMAIS
                         suivi les conseils = lots 'import' conservés tels
                         quels (sans ventes → pas de cash suivi → pas
                         d'achats non plus). L'écart total − buy_hold
                         mesure ce que les conseils suivis ont réellement
                         rapporté ou coûté.
    """
    par_ticker: dict = {}
    cash = 0.0
    bh   = 0.0
    for l in lots:
        t = l.get("ticker", "?")
        q = float(l.get("quantite") or 0)
        p = float(l.get("prix_achat") or 0)
        typ = l.get("type", "achat")
        if typ in ("achat", "import"):
            par_ticker[t] = par_ticker.get(t, 0.0) + q
        elif typ == "vente":
            par_ticker[t] = par_ticker.get(t, 0.0) - q
        if typ == "vente":
            cash += q * p
        elif typ == "achat":
            cash -= q * p
        if typ == "import":
            bh += q * float(prix_par_ticker.get(t) or 0)

    valeur = sum(max(q, 0) * float(prix_par_ticker.get(t) or 0)
                 for t, q in par_ticker.items())
    cash = max(round(cash, 2), 0.0)
    return {
        "valeur_positions": round(valeur, 2),
        "cash":             cash,
        "total":            round(valeur + cash, 2),
        "buy_hold":         round(bh, 2),
    }
