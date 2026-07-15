# flask_app/blueprints/portfolio.py — positions + conseils journaliers

from flask import Blueprint, request, jsonify
from flask_login import current_user, login_required

bp = Blueprint("portfolio", __name__, url_prefix="/portfolio")


# ── Positions ─────────────────────────────────────────────────────────────────

@bp.route("/positions/<ticker>")
@login_required
def get_positions(ticker: str):
    """Retourne positions + résumé P&L pour un ticker (AJAX)."""
    ticker = ticker.upper()
    try:
        from data.market            import get_live_price
        from portfolio.positions    import get_portfolio_summary
        live    = get_live_price(ticker)
        price   = live.get("price") or 0
        summary = get_portfolio_summary(current_user.id, ticker, price)
        return jsonify({"ok": True, "summary": summary, "price": price})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/positions/add", methods=["POST"])
@login_required
def add_position():
    """Ajoute un lot d'achat."""
    data = request.get_json(silent=True) or {}
    ticker       = data.get("ticker", "").strip().upper()
    company      = data.get("company", "").strip()
    date_achat   = data.get("date_achat", "").strip()
    prix_achat   = data.get("prix_achat")
    quantite     = data.get("quantite")
    currency     = data.get("currency", "USD").strip()
    notes        = data.get("notes", "").strip()
    type_op      = data.get("type", "achat").strip()
    conseil_date = data.get("conseil_date") or None

    if not ticker or not date_achat or not prix_achat or not quantite:
        return jsonify({"ok": False, "error": "Champs obligatoires manquants"}), 400
    try:
        prix_achat = float(prix_achat)
        quantite   = float(quantite)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Prix et quantité doivent être des nombres"}), 400
    if prix_achat <= 0 or quantite <= 0:
        return jsonify({"ok": False, "error": "Prix et quantité doivent être positifs"}), 400

    try:
        from portfolio.positions import add_position as _add, get_portfolio_summary

        # Bloquer une vente si pas d'actions disponibles
        if type_op == "vente":
            summary = get_portfolio_summary(current_user.id, ticker, 0)
            available = (summary or {}).get("total_shares", 0)
            if available <= 0:
                return jsonify({"ok": False,
                                "error": f"Vous n'avez pas d'actions {ticker} à vendre."}), 400
            if quantite > available:
                return jsonify({"ok": False,
                                "error": f"Quantité trop élevée — vous avez {available:g} actions {ticker}."}), 400

        row = _add(current_user.id, ticker, company,
                   date_achat, prix_achat, quantite, currency, notes, type_op, conseil_date)

        # Invalide le conseil du jour pour qu'il soit régénéré avec la position à jour
        try:
            from datetime import date
            from db import _init, _client, is_available
            if is_available():
                _init()
                _client.table("daily_advice").delete()\
                    .eq("username", current_user.id)\
                    .eq("ticker", ticker)\
                    .eq("date_conseil", str(date.today()))\
                    .execute()
        except Exception:
            pass

        return jsonify({"ok": True, "position": row})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/positions/delete/<int:position_id>", methods=["DELETE"])
@login_required
def delete_position(position_id: int):
    """Supprime un lot (vérifie l'appartenance)."""
    try:
        from portfolio.positions import delete_position as _del
        ok = _del(position_id, current_user.id)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Vue d'ensemble toutes positions ──────────────────────────────────────────

@bp.route("/overview")
@login_required
def get_overview():
    """
    Retourne toutes les positions de l'utilisateur avec prix live et conseil du jour.
    Une seule requête Supabase pour les positions, une pour les conseils.
    """
    try:
        from portfolio.positions import get_positions, get_portfolio_summary
        from portfolio.advisor   import get_all_today_advice, ACTION_LABELS
        from data.market         import get_live_price

        _SYM = {"USD":"$","EUR":"€","GBP":"£","JPY":"¥","CHF":"Fr","CAD":"CA$","AUD":"A$","HKD":"HK$"}

        all_lots = get_positions(current_user.id)
        if not all_lots:
            return jsonify({"ok": True, "positions": [], "labels": ACTION_LABELS})

        # Tickers uniques, dans l'ordre d'apparition
        tickers = list(dict.fromkeys(l["ticker"] for l in all_lots))

        # Conseils du jour en une seule requête
        advices = get_all_today_advice(current_user.id, tickers)

        from cache import get_cached

        result = []
        for ticker in tickers:
            try:
                live         = get_live_price(ticker)
                price        = live.get("price") or 0
                var_1d       = live.get("var_1d") or 0
                # Logo depuis le cache mémoire (dispo si l'utilisateur a récemment analysé ce ticker)
                cached_snap  = get_cached(ticker)
                logo_url     = (cached_snap or {}).get("market", {}).get("logo_url", "")
                ticker_lots  = [l for l in all_lots if l["ticker"] == ticker]
                if not ticker_lots:
                    continue

                # Calcul summary directement depuis les lots déjà chargés (0 appel DB extra)
                buy_lots      = [l for l in ticker_lots if l.get("type", "achat") in ("achat", "import")]
                sell_lots     = [l for l in ticker_lots if l.get("type") == "vente"]
                if not buy_lots:
                    continue
                total_buy_shares  = sum(float(l["quantite"]) for l in buy_lots)
                total_sell_shares = sum(float(l["quantite"]) for l in sell_lots)
                total_shares      = total_buy_shares - total_sell_shares
                total_buy_amount  = sum(float(l["quantite"]) * float(l["prix_achat"]) for l in buy_lots)
                cout_moyen        = total_buy_amount / total_buy_shares
                valeur            = total_shares * price
                total_sell_amount = sum(float(l["quantite"]) * float(l["prix_achat"]) for l in sell_lots)
                pnl_realise       = total_sell_amount - (total_sell_shares * cout_moyen)
                pnl_non_realise   = total_shares * (price - cout_moyen) if total_shares > 0 else 0
                pnl_total         = pnl_realise + pnl_non_realise
                pnl_pct           = (pnl_total / total_buy_amount * 100) if total_buy_amount > 0 else 0
                currency      = ticker_lots[0].get("currency", "USD")
                company       = next(
                    (l["company"] for l in ticker_lots if l.get("company")), ticker
                )
                result.append({
                    "ticker":   ticker,
                    "company":  company,
                    "currency": currency,
                    "sym":      _SYM.get(currency, "$"),
                    "logo_url": logo_url,
                    "price":    price,
                    "var_1d":   var_1d,
                    "summary": {
                        "lots":            ticker_lots,
                        "total_shares":    round(total_shares,    4),
                        "cout_moyen":      round(cout_moyen,      4),
                        "total_investi":   round(total_buy_amount,2),
                        "valeur_actuelle": round(valeur,          2),
                        "pnl_realise":     round(pnl_realise,     2),
                        "pnl_non_realise": round(pnl_non_realise, 2),
                        "pnl_euros":       round(pnl_total,       2),
                        "pnl_pct":         round(pnl_pct,         2),
                        "position_fermee":  total_shares <= 0,
                    },
                    "advice":  advices.get(ticker),
                })
            except Exception as e:
                print(f"[Overview] {ticker} erreur : {e}", flush=True)

        # Snapshot quotidien après clôture NASDAQ (22h Paris, une fois par jour)
        try:
            from portfolio.history import (save_daily_snapshot,
                                           snapshot_exists_today,
                                           _market_closed_today)
            if result and _market_closed_today() and not snapshot_exists_today(current_user.id):
                save_daily_snapshot(current_user.id, result)
        except Exception:
            pass

        resp = jsonify({"ok": True, "positions": result, "labels": ACTION_LABELS})
        resp.headers["Cache-Control"] = "no-store"
        return resp

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Historique portefeuille ───────────────────────────────────────────────────

@bp.route("/history")
@login_required
def get_history():
    """Retourne les snapshots quotidiens pour le graphe historique."""
    days = request.args.get("days", 90, type=int)
    days = min(max(days, 7), 365)
    try:
        from portfolio.history import get_history as _get
        rows = _get(current_user.id, days)
        return jsonify({"ok": True, "history": rows})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Take Profit / Stop Loss ───────────────────────────────────────────────────

@bp.route("/targets/<ticker>")
@login_required
def get_targets(ticker: str):
    """Retourne les niveaux TP/SL pour un ticker."""
    try:
        from portfolio.targets import get_targets as _get
        data = _get(current_user.id, ticker.upper())
        return jsonify({"ok": True, "targets": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/targets/<ticker>", methods=["POST"])
@login_required
def save_targets(ticker: str):
    """Sauvegarde (upsert) les niveaux TP/SL."""
    data = request.get_json(silent=True) or {}
    tp   = data.get("take_profit")
    sl   = data.get("stop_loss")
    try:
        tp = float(tp) if tp not in (None, "", 0) else None
        sl = float(sl) if sl not in (None, "", 0) else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Valeurs invalides"}), 400
    try:
        from portfolio.targets import save_targets as _save, delete_targets as _del
        if tp is None and sl is None:
            _del(current_user.id, ticker.upper())
            return jsonify({"ok": True, "targets": None})
        row = _save(current_user.id, ticker.upper(), tp, sl)
        return jsonify({"ok": True, "targets": row})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/targets/suggest/<ticker>")
@login_required
def suggest_targets(ticker: str):
    """
    Niveaux TP/SL suggérés depuis les seuils ATR du conseil — les MÊMES
    calculs que l'advisor (atr_pct + seuils_adaptes bornés par la config
    utilisateur), convertis en prix absolus depuis le coût moyen de la
    position. L'utilisateur garde la main : la route ne fait que suggérer,
    c'est lui qui enregistre.
    """
    ticker = ticker.upper()
    try:
        from snapshot                 import get_snapshot, MAX_AGE_HOURS
        from portfolio.positions      import get_portfolio_summary
        from portfolio.risk           import atr_pct, seuils_adaptes
        from portfolio.config_advisor import get_config
        from data.market              import get_live_price

        snap = get_snapshot(ticker, max_age_hours=MAX_AGE_HOURS)
        if not snap:
            return jsonify({"ok": False,
                            "error": "Analyse SDE non disponible — lance d'abord une analyse"})

        prix = (get_live_price(ticker) or {}).get("price") \
               or snap.get("market", {}).get("price") or 0
        summary = get_portfolio_summary(current_user.id, ticker, prix)
        if not summary or summary.get("position_fermee"):
            return jsonify({"ok": False, "error": "Aucune position ouverte"})

        atr    = atr_pct(snap.get("market", {}).get("history"))
        seuils = seuils_adaptes(get_config(current_user.id), atr)
        if not seuils["adapte"]:
            return jsonify({"ok": False,
                            "error": "ATR indisponible (historique insuffisant)"})

        # Les seuils sont des % de P&L vs COÛT MOYEN (mêmes bases que
        # l'advisor) → conversion en prix absolus pour les champs TP/SL
        cout = float(summary["cout_moyen"])
        return jsonify({
            "ok":        True,
            "atr_pct":   atr,
            "cout_moyen": round(cout, 4),
            "stop_loss":   round(cout * (1 + seuils["stop_loss_pct"]   / 100), 4),
            "take_profit": round(cout * (1 + seuils["take_profit_pct"] / 100), 4),
            "sl_pct":    seuils["stop_loss_pct"],
            "tp_pct":    seuils["take_profit_pct"],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Conseil du jour ───────────────────────────────────────────────────────────

@bp.route("/advice/<ticker>/reset", methods=["POST"])
@login_required
def reset_advice(ticker: str):
    """Supprime le conseil du jour pour forcer sa régénération."""
    ticker = ticker.upper()
    try:
        from datetime import date
        from db import _init, _client, is_available
        if is_available():
            _init()
            _client.table("daily_advice").delete()\
                .eq("username", current_user.id)\
                .eq("ticker", ticker)\
                .eq("date_conseil", str(date.today()))\
                .execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/advice/<ticker>")
@login_required
def get_advice(ticker: str):
    """
    Retourne le conseil du jour pour ce ticker.
    Le génère à la volée si pas encore créé aujourd'hui, le sauvegarde dans Supabase.
    """
    ticker = ticker.upper()
    try:
        from portfolio.advisor   import (get_today_advice, generate_advice,
                                          save_advice, get_advice_history,
                                          ACTION_LABELS)
        from portfolio.positions import get_portfolio_summary
        from data.market         import get_live_price
        from snapshot            import get_snapshot, MAX_AGE_HOURS

        # Prix live
        live  = get_live_price(ticker)
        price = live.get("price") or 0

        # Conseil déjà généré aujourd'hui ?
        advice_row = get_today_advice(current_user.id, ticker)

        if not advice_row:
            # Snapshot SDE (analyse du jour)
            snap = get_snapshot(ticker, max_age_hours=MAX_AGE_HOURS)
            if not snap:
                return jsonify({"ok": False, "error": "Analyse SDE non disponible — lance d'abord une analyse"}), 404

            # Prix ET variation du jour LIVE — le var_1d du snapshot date
            # de sa génération (souvent la veille) : un pattern baissier
            # d'hier doit pouvoir être invalidé par le rebond d'aujourd'hui
            market  = {**snap.get("market", {}),
                       "price": price or snap["market"].get("price")}
            if live.get("var_1d") is not None:
                market["var_1d"] = live["var_1d"]
            summary = get_portfolio_summary(current_user.id, ticker, price)

            # Pattern chandelier depuis l'historique du snapshot
            candle_info = None
            try:
                from analysis.candle_patterns import detect_patterns
                hist = snap.get("market", {}).get("history")
                if hist is not None and len(hist) > 0:
                    pat_df = detect_patterns(hist.tail(60))
                    if not pat_df.empty:
                        last = pat_df.iloc[-1]
                        raw_date = last.get("date") if hasattr(last, "get") else last["date"]
                        try:
                            candle_date_str = raw_date.strftime("%d.%m.%Y")
                        except Exception:
                            parts = str(raw_date)[:10].split("-")
                            candle_date_str = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else ""
                        candle_info = {
                            "signal":      last["signal"],
                            "pattern":     last["pattern"],
                            "description": last.get("description", ""),
                            "date":        candle_date_str,
                        }
            except Exception as _ce:
                print(f"[Advice] detect_patterns erreur : {_ce}", flush=True)

            from portfolio.config_advisor import get_config as _get_cfg
            from portfolio.positions import get_cash_disponible
            advice  = generate_advice(summary, market, snap,
                                      candle_info=candle_info,
                                      cfg=_get_cfg(current_user.id),
                                      cash_dispo=get_cash_disponible(current_user.id))
            advice_row = save_advice(current_user.id, ticker, advice, market, snap)

        # Historique des 14 derniers conseils
        history = get_advice_history(current_user.id, ticker, limit=14)

        # Statistiques sur l'historique évalué — J+1 (réactivité) et J+20
        # (l'horizon aligné sur les signaux 14-50j, celui qui fait foi)
        evaluated = [h for h in history if h.get("bon_conseil") is not None]
        ev_j20    = [h for h in history if h.get("bon_conseil_j20") is not None]
        stats = {
            "total":    len(evaluated),
            "bons":     sum(1 for h in evaluated if h["bon_conseil"]),
            "mauvais":  sum(1 for h in evaluated if not h["bon_conseil"]),
            "taux_pct": round(sum(1 for h in evaluated if h["bon_conseil"]) / len(evaluated) * 100)
                        if evaluated else None,
            "total_j20":    len(ev_j20),
            "taux_j20_pct": round(sum(1 for h in ev_j20 if h["bon_conseil_j20"]) / len(ev_j20) * 100)
                            if ev_j20 else None,
        }

        return jsonify({
            "ok":      True,
            "advice":  advice_row,
            "history": history,
            "stats":   stats,
            "labels":  ACTION_LABELS,
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc(), flush=True)   # trace dans les logs, PAS au client
        return jsonify({"ok": False, "error": "Erreur interne — voir les logs serveur."}), 500
