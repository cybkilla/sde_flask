# flask_app/blueprints/cron.py — endpoint HTTP pour le scheduler (cron-job.org)
import threading
from flask import Blueprint, request, jsonify
from config import CRON_SECRET

bp = Blueprint("cron", __name__, url_prefix="/scheduler")

# Verrou pour éviter deux exécutions simultanées (retry cron-job.org)
_lock = threading.Lock()


def _check_secret() -> bool:
    token = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    return bool(CRON_SECRET) and token == CRON_SECRET


@bp.route("/run", methods=["GET", "POST"])
def run_scheduler():
    """
    Endpoint appelé par cron-job.org toutes les 30 minutes.
    Retourne 202 immédiatement — le scheduler tourne en thread background.
    Protégé par X-Cron-Secret (header) ou ?secret= (query param).
    Retourne 403 (pas 401) pour ne pas déclencher le handler Flask-Login.
    """
    if not _check_secret():
        return jsonify({"error": "Token invalide ou absent"}), 403

    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "message": "Scheduler déjà en cours d'exécution"}), 429

    def _run():
        import sys, traceback
        try:
            print("[Cron] Thread scheduler démarré", flush=True)
            from alerts.scheduler import check_all
            check_all()
            print("[Cron] Thread scheduler terminé", flush=True)
        except Exception as e:
            sys.stderr.write(f"[Cron] ERREUR : {e}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
        finally:
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Scheduler lancé en arrière-plan"}), 202


@bp.route("/test-email", methods=["GET", "POST"])
def test_email():
    """
    Envoie un email de test Resend à l'adresse indiquée (?to=...) ou au premier
    utilisateur trouvé. Permet de valider la chaîne Resend sans déclencher
    le pipeline complet.
    Protégé par le même secret que /run.
    """
    if not _check_secret():
        return jsonify({"error": "Token invalide ou absent"}), 403

    to_email = request.args.get("to", "").strip()
    if not to_email:
        # Récupère l'email du premier utilisateur enregistré
        try:
            from alerts.scheduler import get_all_users
            users = get_all_users()
            if users:
                to_email = next(iter(users.values()))
        except Exception:
            pass

    if not to_email:
        return jsonify({"error": "Aucune adresse email trouvée. Passez ?to=votre@email.com"}), 400

    import traceback
    try:
        import resend as _resend
        from config import RESEND_API_KEY, RESEND_FROM

        if not RESEND_API_KEY:
            return jsonify({"ok": False, "error": "RESEND_API_KEY absente dans les variables Render"}), 500

        _resend.api_key = RESEND_API_KEY
        result = _resend.Emails.send({
            "from":    RESEND_FROM,
            "to":      [to_email],
            "subject": "[SDE] Test email Resend",
            "html":    "<p>Test Resend OK — si vous recevez cet email, la configuration fonctionne.</p>",
        })
        return jsonify({"ok": True, "to": to_email, "resend_from": RESEND_FROM, "resend_response": str(result)}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500
