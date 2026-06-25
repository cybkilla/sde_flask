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

    buy_lots  = [l for l in lots if l.get("type", "achat") == "achat"]
    sell_lots = [l for l in lots if l.get("type") == "vente"]

    if not buy_lots:
        return None

    total_buy_shares  = sum(float(l["quantite"]) for l in buy_lots)
    total_sell_shares = sum(float(l["quantite"]) for l in sell_lots)
    total_shares      = total_buy_shares - total_sell_shares

    total_buy_amount  = sum(float(l["quantite"]) * float(l["prix_achat"]) for l in buy_lots)
    cout_moyen        = total_buy_amount / total_buy_shares

    # P&L non réalisé sur les actions restantes
    valeur_actuelle = total_shares * (current_price or 0)
    total_investi   = total_shares * cout_moyen  # coût de la position restante
    pnl_euros       = total_shares * ((current_price or 0) - cout_moyen)
    pnl_pct         = (pnl_euros / total_investi * 100) if total_investi > 0 else 0

    return {
        "lots":             lots,
        "total_shares":     round(total_shares,     4),
        "cout_moyen":       round(cout_moyen,        4),
        "total_investi":    round(total_investi,     2),
        "valeur_actuelle":  round(valeur_actuelle,   2),
        "pnl_euros":        round(pnl_euros,         2),
        "pnl_pct":          round(pnl_pct,           2),
        "currency":         lots[0].get("currency", "USD"),
        "position_fermee":  total_shares <= 0,
    }


# ── Écriture ──────────────────────────────────────────────────────────────────

def add_position(username: str, ticker: str, company: str,
                 date_achat: str, prix_achat: float,
                 quantite: float, currency: str = "USD", notes: str = "",
                 type_op: str = "achat") -> dict:
    """Insère un lot d'achat ou de vente. Retourne la ligne créée."""
    ticker = ticker.upper()
    row = {
        "username":   username,
        "ticker":     ticker,
        "company":    company,
        "date_achat": str(date_achat),
        "prix_achat": float(prix_achat),
        "quantite":   float(quantite),
        "currency":   currency,
        "notes":      notes,
        "type":       type_op if type_op in ("achat", "vente") else "achat",
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
