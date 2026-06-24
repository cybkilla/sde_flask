# flask_app/blueprints/cron.py — endpoint HTTP pour le scheduler (cron-job.org)
from flask import Blueprint, request, jsonify
from flask_wtf.csrf import CSRFProtect
from config import CRON_SECRET

bp = Blueprint("cron", __name__, url_prefix="/scheduler")


@bp.route("/run", methods=["GET", "POST"])
def run_scheduler():
    """
    Endpoint appelé par cron-job.org toutes les 30 minutes.
    Protégé par le header X-Cron-Secret ou le paramètre ?secret=...
    Retourne 403 (pas 401) pour ne pas déclencher le handler Flask-Login.
    """
    token = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    if not CRON_SECRET or token != CRON_SECRET:
        return jsonify({"error": "Token invalide ou absent"}), 403

    try:
        from alerts.scheduler import check_all
        check_all()
        return jsonify({"ok": True, "message": "Scheduler exécuté avec succès"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
