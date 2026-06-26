# flask_app/blueprints/admin.py — Dashboard admin pertinence des conseils

import os
import hmac
from flask import Blueprint, render_template, jsonify, request, abort
from flask_login import current_user, login_required

bp = Blueprint("admin", __name__, url_prefix="/admin")

_ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]


def _require_admin():
    if not current_user.is_authenticated:
        abort(403)
    if _ADMIN_EMAILS and current_user.email not in _ADMIN_EMAILS:
        abort(403)


@bp.route("/")
@login_required
def dashboard():
    _require_admin()
    return render_template("admin.html")


@bp.route("/advisor-config", methods=["GET"])
@login_required
def get_advisor_config():
    _require_admin()
    from portfolio.config_advisor import get_config, DEFAULTS
    cfg = get_config(current_user.id)
    return jsonify({"ok": True, "config": cfg, "defaults": DEFAULTS})


@bp.route("/advisor-config", methods=["POST"])
@login_required
def save_advisor_config():
    _require_admin()
    data = request.get_json(silent=True) or {}
    try:
        from portfolio.config_advisor import save_config, reset_config
        if data.get("reset"):
            reset_config(current_user.id)
            from portfolio.config_advisor import DEFAULTS
            return jsonify({"ok": True, "config": DEFAULTS})
        cfg = save_config(current_user.id, data)
        return jsonify({"ok": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# Tables à réinitialiser/supprimer par utilisateur (table, colonne username)
_USER_TABLES = [
    ("positions",           "username"),
    ("daily_advice",        "username"),
    ("watchlist",           "username"),
    ("portfolio_snapshots", "username"),
    ("position_targets",    "username"),
    ("advisor_config",      "username"),
    ("weekly_reports",      "username"),
]


def _check_data_password(provided: str) -> bool:
    expected = os.getenv("ADMIN_DATA_PASSWORD", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.strip(), provided.strip())


@bp.route("/users")
@login_required
def list_users():
    _require_admin()
    try:
        from db import find, is_available
        if not is_available():
            return jsonify({"ok": False, "error": "Supabase indisponible"})
        rows = find("users", {}) or []
        users = [{"username": r["username"], "email": r.get("email", "")} for r in rows]
        return jsonify({"ok": True, "users": users})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/data/reset", methods=["POST"])
@login_required
def data_reset():
    """Réinitialise les données opérationnelles d'un user (ou tous), conserve les comptes."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    if not _check_data_password(data.get("password", "")):
        return jsonify({"ok": False, "error": "Mot de passe incorrect"}), 403

    target = data.get("target", "")  # username ou "__all__"
    if not target:
        return jsonify({"ok": False, "error": "Cible manquante"}), 400

    try:
        from db import _init, _client, is_available
        if not is_available():
            return jsonify({"ok": False, "error": "Supabase indisponible"})
        _init()

        if target == "__all__":
            rows = _client.table("users").select("username").execute().data or []
            usernames = [r["username"] for r in rows]
        else:
            usernames = [target]

        if not usernames:
            return jsonify({"ok": True, "message": "Aucun utilisateur trouvé"})

        summary = {}
        for table, col in _USER_TABLES:
            try:
                res = _client.table(table).delete().in_(col, usernames).execute()
                summary[table] = len(res.data or [])
            except Exception as e:
                summary[table] = f"erreur: {e}"

        scope = "tous les utilisateurs" if target == "__all__" else target
        print(f"[Admin] Réinitialisation : {scope} par {current_user.id}", flush=True)
        return jsonify({"ok": True, "scope": scope, "summary": summary})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/data/delete", methods=["POST"])
@login_required
def data_delete():
    """Supprime un compte utilisateur et toutes ses données. Interdit pour Admin et soi-même."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    if not _check_data_password(data.get("password", "")):
        return jsonify({"ok": False, "error": "Mot de passe incorrect"}), 403

    username = data.get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "error": "Utilisateur manquant"}), 400
    if username.lower() == "admin":
        return jsonify({"ok": False, "error": "Impossible de supprimer le compte Admin"}), 400
    if username == current_user.id:
        return jsonify({"ok": False, "error": "Impossible de supprimer votre propre compte"}), 400

    try:
        from db import _init, _client, is_available
        if not is_available():
            return jsonify({"ok": False, "error": "Supabase indisponible"})
        _init()

        for table, col in _USER_TABLES:
            try:
                _client.table(table).delete().eq(col, username).execute()
            except Exception:
                pass

        _client.table("users").delete().eq("username", username).execute()
        print(f"[Admin] Suppression compte : {username} par {current_user.id}", flush=True)
        return jsonify({"ok": True, "deleted_user": username})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
