# flask_app/blueprints/stock.py

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from flask_login import current_user, login_required

bp = Blueprint("stock", __name__)

_CURRENCY_SYM = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
    "CHF": "Fr", "CAD": "CA$", "AUD": "A$", "HKD": "HK$",
}


# ── Home ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def home():
    return render_template("home.html")


# ── Autocomplete search ───────────────────────────────────────────────────────

@bp.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        from utils.ticker_search import search_tickers
        df = search_tickers(q)
        if df.empty:
            return jsonify([])
        df = df.rename(columns={"nom": "shortName"})
        return jsonify(df[["ticker", "shortName", "exchange"]].to_dict(orient="records"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Analyse ───────────────────────────────────────────────────────────────────

@bp.route("/analyze/<ticker>")
def analyze(ticker: str):
    ticker = ticker.upper().strip()
    if not ticker or ticker == "_":
        return redirect(url_for("stock.home"))

    # ── Pipeline ──────────────────────────────────────────
    nocache = request.args.get("nocache") == "1"
    if nocache:
        from cache import clear_cache
        clear_cache()
    try:
        from pipeline import run
        res = run(ticker, use_cache=not nocache)
    except Exception as exc:
        flash(f"Erreur lors de l'analyse de {ticker} : {exc}", "danger")
        return redirect(url_for("stock.home"))

    market = res["market"]
    sym    = _CURRENCY_SYM.get(market.get("currency", "USD"), "$")

    # ── Zones de trading ──────────────────────────────────
    zones = None
    try:
        from analysis.trading_zones import compute_trading_zones
        zones = compute_trading_zones(
            market["history"], market,
            res["score_global"], res["recommandation"],
        )
    except Exception:
        pass

    # ── Signaux détaillés ─────────────────────────────────
    signals_list = []
    try:
        from analysis.explainer import build_explanation_df
        signals_list = build_explanation_df(res).to_dict(orient="records")
    except Exception:
        pass

    # ── Explication figure chartiste (dernier pattern détecté) ────
    candle_pattern = None
    try:
        from analysis.candle_patterns import detect_patterns
        _pat_df = detect_patterns(market["history"].tail(60))
        if not _pat_df.empty:
            last   = _pat_df.iloc[-1]
            signal = last["signal"]
            reco   = res["recommandation"]
            score  = res["score_global"]

            jours = (market["history"].index[-1].date() - last["date"].date()).days
            delai = "aujourd'hui" if jours == 0 else f"il y a {jours} jour{'s' if jours > 1 else ''}"

            _ico = {"bullish": "📈", "bearish": "📉", "neutre": "🔶"}
            p1 = (
                f"{_ico.get(signal, '🔶')} **{last['pattern']}** détecté {delai} "
                f"*(signal court terme, 1–5 jours)* — {last['description']}."
            )

            agrees     = (signal == "bullish" and reco == "ACHETER") or \
                         (signal == "bearish" and reco == "VENDRE")
            contradicts = (signal == "bullish" and reco == "VENDRE") or \
                          (signal == "bearish" and reco == "ACHETER")

            if signal == "neutre":
                p2 = (
                    f"La recommandation moyen terme (14–50 j) reste **{reco}** "
                    f"({score:.0f}/100) — cette indécision court terme ne remet pas en cause la tendance de fond."
                )
            elif agrees:
                p2 = (
                    f"Ce signal renforce la recommandation **{reco}** ({score:.0f}/100) "
                    f"issue du score moyen terme (14–50 j) — les deux horizons convergent."
                )
            elif contradicts:
                if signal == "bearish":
                    p2 = (
                        f"La recommandation moyen terme (14–50 j) reste **{reco}** "
                        f"({score:.0f}/100) — ce repli court terme peut être une consolidation "
                        f"temporaire avant reprise, à surveiller sans paniquer."
                    )
                else:
                    p2 = (
                        f"La recommandation moyen terme (14–50 j) reste **{reco}** "
                        f"({score:.0f}/100) — ce rebond court terme peut être technique "
                        f"et non durable, prudence avant de renforcer."
                    )
            else:
                if reco == "NEUTRE":
                    p2 = (
                        f"Le score global est **NEUTRE** ({score:.0f}/100, horizon 14–50 j) — "
                        f"ce signal court terme est à surveiller, mais une confirmation "
                        f"sur plusieurs jours est recommandée avant d'agir."
                    )
                else:
                    p2 = (
                        f"La recommandation moyen terme est **{reco}** "
                        f"({score:.0f}/100, horizon 14–50 j) — l'indécision court terme "
                        f"ne modifie pas cette perspective."
                    )

            import re as _re
            def _md_bold(s):
                return _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)

            candle_pattern = {
                "signal":  signal,
                "pattern": last["pattern"],
                "p1":      _md_bold(p1),
                "p2":      _md_bold(p2),
            }
    except Exception:
        pass

    # ── News — nettoyage colonnes ─────────────────────────
    _news_cols = ["type", "titre", "url", "sentiment_label", "sentiment_score", "date", "source"]
    df_news = res["df_news"][[c for c in _news_cols if c in res["df_news"].columns]].copy()
    if "type"  not in df_news.columns: df_news["type"] = "ticker"
    if "date"  in df_news.columns:
        df_news["date"] = df_news["date"].fillna("").astype(str).str[:10]
    df_news["url"] = df_news["url"].fillna("").astype(str)
    from config import MAX_NEWS_DISPLAY
    news_list = df_news.head(MAX_NEWS_DISPLAY).to_dict(orient="records")

    # ── Insider ───────────────────────────────────────────
    insider_list = (
        res["df_insider"].to_dict(orient="records")
        if not res["df_insider"].empty else []
    )

    # ── Scores table ──────────────────────────────────────
    _horizons = {"Technique": "14–50 j", "Fondamental": "trimestriel", "Médiatique": "7–30 j"}
    scores_list = []
    for row in res["df_scores"].to_dict(orient="records"):
        row["horizon"] = _horizons.get(row["composante"], "")
        scores_list.append(row)

    # ── Graphiques ────────────────────────────────────────
    charts = {}
    try:
        from flask_app.charts_helpers import build_charts
        charts = build_charts(market["history"], ticker)
    except Exception:
        pass

    # ── Watchlist : ticker déjà présent ? ─────────────────
    in_watchlist = False
    if current_user.is_authenticated:
        try:
            from watchlist.watchlist import get_watchlist
            in_watchlist = any(
                i["ticker"] == ticker for i in get_watchlist(current_user.id)
            )
        except Exception:
            pass

    return render_template(
        "analysis.html",
        ticker       = ticker,
        res          = res,
        market       = market,
        sym          = sym,
        zones        = zones,
        scores_list  = scores_list,
        signals_list = signals_list,
        news_list    = news_list,
        insider_list = insider_list,
        charts         = charts,
        in_watchlist   = in_watchlist,
        candle_pattern = candle_pattern,
    )


# ── Watchlist (AJAX) ─────────────────────────────────────────────────────────

@bp.route("/watchlist/add", methods=["POST"])
@login_required
def watchlist_add():
    data    = request.get_json(silent=True) or {}
    ticker  = data.get("ticker", "").strip().upper()
    company = data.get("company", "").strip()
    if not ticker:
        return jsonify({"error": "ticker manquant"}), 400
    from watchlist.watchlist import add_ticker
    add_ticker(current_user.id, ticker, company)
    return jsonify({"ok": True, "ticker": ticker})


@bp.route("/watchlist/remove", methods=["POST"])
@login_required
def watchlist_remove():
    data   = request.get_json(silent=True) or {}
    ticker = data.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker manquant"}), 400
    from watchlist.watchlist import remove_ticker
    remove_ticker(current_user.id, ticker)
    return jsonify({"ok": True, "ticker": ticker})


@bp.route("/watchlist")
@login_required
def watchlist_list():
    from watchlist.watchlist import get_watchlist
    return jsonify(get_watchlist(current_user.id))
