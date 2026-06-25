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
    ticker     = data.get("ticker", "").strip().upper()
    company    = data.get("company", "").strip()
    date_achat = data.get("date_achat", "").strip()
    prix_achat = data.get("prix_achat")
    quantite   = data.get("quantite")
    currency   = data.get("currency", "USD").strip()
    notes      = data.get("notes", "").strip()

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
        from portfolio.positions import add_position as _add
        row = _add(current_user.id, ticker, company,
                   date_achat, prix_achat, quantite, currency, notes)

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

            market  = {**snap.get("market", {}), "price": price or snap["market"].get("price")}
            summary = get_portfolio_summary(current_user.id, ticker, price)
            advice  = generate_advice(summary, market, snap)
            advice_row = save_advice(current_user.id, ticker, advice, market, snap)

        # Historique des 14 derniers conseils
        history = get_advice_history(current_user.id, ticker, limit=14)

        # Statistiques sur l'historique évalué
        evaluated = [h for h in history if h.get("bon_conseil") is not None]
        stats = {
            "total":    len(evaluated),
            "bons":     sum(1 for h in evaluated if h["bon_conseil"]),
            "mauvais":  sum(1 for h in evaluated if not h["bon_conseil"]),
            "taux_pct": round(sum(1 for h in evaluated if h["bon_conseil"]) / len(evaluated) * 100)
                        if evaluated else None,
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
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500
