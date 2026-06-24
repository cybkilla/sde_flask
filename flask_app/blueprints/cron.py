# flask_app/blueprints/cron.py — endpoint HTTP pour le scheduler (cron-job.org)
import threading
from flask import Blueprint, request, jsonify
from config import CRON_SECRET

bp = Blueprint("cron", __name__, url_prefix="/scheduler")

# Verrou pour éviter deux exécutions simultanées (retry cron-job.org)
_lock = threading.Lock()


@bp.route("/run", methods=["GET", "POST"])
def run_scheduler():
    """
    Endpoint appelé par cron-job.org toutes les 30 minutes.
    Retourne 202 immédiatement — le scheduler tourne en thread background.
    Protégé par X-Cron-Secret (header) ou ?secret= (query param).
    Retourne 403 (pas 401) pour ne pas déclencher le handler Flask-Login.
    """
    token = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    if not CRON_SECRET or token != CRON_SECRET:
        return jsonify({"error": "Token invalide ou absent"}), 403

    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "message": "Scheduler déjà en cours d'exécution"}), 429

    def _run():
        try:
            from alerts.scheduler import check_all
            check_all()
        except Exception as e:
            print(f"[Cron] Erreur scheduler : {e}")
        finally:
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Scheduler lancé en arrière-plan"}), 202
