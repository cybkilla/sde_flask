# flask_app/blueprints/stock.py — routes principales
# J1  : stubs home + api/search + analyze/<ticker>
# J4  : implémentation autocomplete search
# J5  : implémentation pipeline + rendu analysis.html
# J7  : watchlist (add/remove via AJAX)

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from flask_login import current_user, login_required

bp = Blueprint("stock", __name__)


# ── J1 : Home ─────────────────────────────────────────────────────────────────

@bp.route("/")
def home():
    return render_template("home.html")


# ── J4 : Autocomplete search (endpoint AJAX) ───────────────────────────────────

@bp.route("/api/search")
def api_search():
    """
    GET /api/search?q=apple
    Retourne une liste JSON [{ticker, shortName}, …]
    Branché sur utils/ticker_search.py — inchangé depuis Streamlit.
    """
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    try:
        from utils.ticker_search import search_tickers
        df = search_tickers(q)
        return jsonify([] if df.empty else df.to_dict(orient="records"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── J5 : Analyse (stub → implémentation complète J5) ─────────────────────────

@bp.route("/analyze/<ticker>")
def analyze(ticker: str):
    """
    Stub J1 — affiche l'en-tête du ticker.
    J5 : appel pipeline.run(ticker) + rendu complet.
    """
    ticker = ticker.upper().strip()
    if not ticker or ticker == "_":
        return redirect(url_for("stock.home"))

    # TODO J5 : remplacer par le vrai pipeline
    result = None  # pipeline.run(ticker)

    return render_template("analysis.html", ticker=ticker, result=result)


# ── J7 : Watchlist (stubs AJAX) ───────────────────────────────────────────────

@bp.route("/watchlist/add", methods=["POST"])
@login_required
def watchlist_add():
    """POST JSON {ticker, company} → ajoute à la watchlist."""
    # TODO J7
    data   = request.get_json(silent=True) or {}
    ticker = data.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker manquant"}), 400
    # from watchlist.watchlist import add_ticker
    # add_ticker(current_user.username, ticker, data.get("company", ""))
    return jsonify({"ok": True, "ticker": ticker})


@bp.route("/watchlist/remove", methods=["POST"])
@login_required
def watchlist_remove():
    """POST JSON {ticker} → retire de la watchlist."""
    # TODO J7
    data   = request.get_json(silent=True) or {}
    ticker = data.get("ticker", "").strip().upper()
    return jsonify({"ok": True, "ticker": ticker})


@bp.route("/watchlist")
@login_required
def watchlist_list():
    """GET → retourne la watchlist de l'utilisateur connecté."""
    # TODO J7
    # from watchlist.watchlist import get_watchlist
    # items = get_watchlist(current_user.username)
    return jsonify([])
