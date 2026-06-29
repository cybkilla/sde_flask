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

    try:
        from alerts.mailer import send_alert
        send_alert(
            to_email      = to_email,
            username      = "test_user",
            ticker        = "AAPL",
            company       = "Apple Inc.",
            old_reco      = "NEUTRE",
            new_reco      = "ACHETER",
            score         = 72.5,
            prix          = 213.49,
            variation     = 6.3,
            reco_changed  = True,
            var_triggered = True,
            context       = "Test de l'envoi email via Resend. Si vous recevez cet email, la configuration fonctionne correctement.",
        )
        return jsonify({"ok": True, "message": f"Email de test envoyé à {to_email}"}), 200
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


@bp.route("/test-weekly", methods=["GET", "POST"])
def test_weekly():
    """
    Force l'envoi du rapport hebdomadaire pour un utilisateur donné (?to=email).
    Bypass le guard dimanche/22h et l'anti-doublon Supabase.
    Protégé par le même secret que /run.
    """
    if not _check_secret():
        return jsonify({"error": "Token invalide ou absent"}), 403

    to_email = request.args.get("to", "").strip()
    username = request.args.get("user", "").strip()

    try:
        from alerts.scheduler import get_all_users
        from watchlist.watchlist import get_watchlist
        users = get_all_users()

        if not username:
            username = next(iter(users), None)
        if not to_email:
            to_email = users.get(username, "")

        if not username or not to_email:
            return jsonify({"error": "Impossible de trouver utilisateur/email. Passez ?user=X&to=email"}), 400

        watchlist    = get_watchlist(username) or []
        from portfolio.positions import get_positions
        positions    = get_positions(username)
        pos_tickers  = list({r["ticker"] for r in positions})
        debug = {
            "username":  username,
            "email":     to_email,
            "watchlist": [i["ticker"] for i in watchlist],
            "positions": pos_tickers,
        }

        from alerts.weekly_report import send_weekly_report
        send_weekly_report(username, to_email, watchlist)
        return jsonify({"ok": True, "message": f"Envoyé à {to_email}", **debug}), 200
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e),
                        "debug": debug if "debug" in dir() else {},
                        "trace": traceback.format_exc()}), 500
