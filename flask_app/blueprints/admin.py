# flask_app/blueprints/admin.py — Dashboard admin pertinence des conseils

import os
from flask import Blueprint, render_template, jsonify, abort
from flask_login import current_user, login_required

bp = Blueprint("admin", __name__, url_prefix="/admin")

_ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]


def _require_admin():
    if not current_user.is_authenticated:
        abort(403)
    if _ADMIN_EMAILS and current_user.id not in _ADMIN_EMAILS:
        abort(403)


@bp.route("/")
@login_required
def dashboard():
    _require_admin()
    return render_template("admin.html")


@bp.route("/stats")
@login_required
def stats():
    _require_admin()
    try:
        from portfolio.evaluator import evaluate_pending, get_global_stats
        eval_result = evaluate_pending(days_back=90)
        global_stats = get_global_stats()
        return jsonify({"ok": True, "eval": eval_result, "stats": global_stats})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500
