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
    # Fail-closed : sans ADMIN_EMAILS configurée, PERSONNE n'est admin.
    # (L'ancien `if _ADMIN_EMAILS and ...` faisait l'inverse : liste vide
    # → tout utilisateur connecté devenait admin, silencieusement.)
    if not _ADMIN_EMAILS:
        print("[Admin] ADMIN_EMAILS non configurée — accès admin refusé "
              "à tous (fail-closed)", flush=True)
        abort(403)
    if current_user.email not in _ADMIN_EMAILS:
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


@bp.route("/data/reset-password", methods=["POST"])
@login_required
def data_reset_password():
    """Envoie un lien de réinitialisation de mot de passe à l'utilisateur cible."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    if not _check_data_password(data.get("password", "")):
        return jsonify({"ok": False, "error": "Mot de passe incorrect"}), 403

    username = data.get("username", "").strip()
    if not username or username == "__all__":
        return jsonify({"ok": False, "error": "Sélectionnez un utilisateur précis"}), 400

    try:
        from db import find_one, is_available
        if not is_available():
            return jsonify({"ok": False, "error": "Supabase indisponible"})
        user = find_one("users", {"username": username})
        if not user:
            return jsonify({"ok": False, "error": "Utilisateur introuvable"}), 404
        email = user.get("email", "")
        if not email:
            return jsonify({"ok": False, "error": f"Aucun email associé au compte {username}"}), 400

        from auth.auth_tokens import generate, send_reset
        token = generate(username, "reset", hours=24)
        if not token:
            return jsonify({"ok": False, "error": "Impossible de générer le token"}), 500
        sent = send_reset(email, username, token)
        if not sent:
            return jsonify({"ok": False, "error": "Erreur envoi email (vérifiez RESEND_API_KEY)"}), 500

        print(f"[Admin] Reset password envoyé à {email} ({username}) par {current_user.id}", flush=True)
        return jsonify({"ok": True, "email": email})
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


@bp.route("/data/positions/<username>")
@login_required
def list_user_positions(username):
    """Retourne toutes les positions d'un utilisateur, groupées par ticker."""
    _require_admin()
    try:
        from db import _init, _client, is_available
        if not is_available():
            return jsonify({"ok": False, "error": "Supabase indisponible"})
        _init()
        rows = (
            _client.table("positions")
            .select("id,ticker,company,date_achat,prix_achat,quantite,type,conseil_date")
            .eq("username", username)
            .order("ticker")
            .order("date_achat")
            .execute()
            .data or []
        )
        # Group by ticker
        by_ticker: dict = {}
        for r in rows:
            t = r["ticker"]
            g = by_ticker.setdefault(t, {
                "ticker": t, "company": r.get("company", ""),
                "lots": 0, "total_achat": 0.0, "total_vente": 0.0,
                "rows": [],
            })
            g["lots"] += 1
            qty = float(r.get("quantite") or 0)
            if r.get("type") == "vente":
                g["total_vente"] += qty
            else:
                g["total_achat"] += qty
            g["rows"].append(r)
        tickers = [
            {**v, "net_shares": round(v["total_achat"] - v["total_vente"], 4)}
            for v in by_ticker.values()
        ]
        return jsonify({"ok": True, "tickers": tickers})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/data/delete-position", methods=["POST"])
@login_required
def delete_position():
    """Supprime toutes les positions d'un ticker pour un utilisateur, et ses données liées."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    if not _check_data_password(data.get("password", "")):
        return jsonify({"ok": False, "error": "Mot de passe incorrect"}), 403

    username = data.get("username", "").strip()
    ticker   = data.get("ticker", "").strip().upper()
    delete_related = bool(data.get("delete_related", True))

    if not username or not ticker:
        return jsonify({"ok": False, "error": "Utilisateur et ticker requis"}), 400

    try:
        from db import _init, _client, is_available
        if not is_available():
            return jsonify({"ok": False, "error": "Supabase indisponible"})
        _init()

        res = _client.table("positions").delete().eq("username", username).eq("ticker", ticker).execute()
        deleted = {"positions": len(res.data or [])}

        if delete_related:
            try:
                r2 = _client.table("position_targets").delete().eq("username", username).eq("ticker", ticker).execute()
                deleted["position_targets"] = len(r2.data or [])
            except Exception:
                deleted["position_targets"] = 0
            try:
                r3 = _client.table("daily_advice").delete().eq("username", username).eq("ticker", ticker).execute()
                deleted["daily_advice"] = len(r3.data or [])
            except Exception:
                deleted["daily_advice"] = 0

        print(f"[Admin] Suppression position {ticker}/{username} par {current_user.id}: {deleted}", flush=True)
        return jsonify({"ok": True, "ticker": ticker, "username": username, "deleted": deleted})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/stats")
@login_required
def stats():
    _require_admin()
    try:
        from portfolio.evaluator import evaluate_pending, reset_intraday_evals, get_global_stats
        reset_intraday_evals()     # Invalide les évaluations faites hors fenêtre (20h-22h)
        eval_result  = evaluate_pending(days_back=90)
        global_stats = get_global_stats()
        return jsonify({"ok": True, "eval": eval_result, "stats": global_stats})
    except Exception as e:
        import traceback
        print(traceback.format_exc(), flush=True)   # trace dans les logs, PAS au client
        return jsonify({"ok": False, "error": "Erreur interne — voir les logs serveur."}), 500


# ── Scan d'opportunités (Top 5 potentiel court terme) ─────────────────────
# Entonnoir à 2 étages (analysis/screener.py) déclenché à la demande —
# jamais par cron, pour ne consommer les quotas API que si l'admin a
# effectivement du cash à placer ce jour-là.

@bp.route("/opportunites")
@login_required
def opportunites():
    _require_admin()
    from analysis.screener import get_scan_state, get_univers_actif, get_suggestion_state
    from portfolio.positions import get_cash_disponible
    return render_template(
        "admin_opportunites.html",
        state=get_scan_state(),
        suggestion_state=get_suggestion_state(),
        cash_dispo=get_cash_disponible(current_user.id),
        univers_actif=get_univers_actif(),
    )


@bp.route("/opportunites/scan", methods=["POST"])
@login_required
def opportunites_scan():
    _require_admin()
    from analysis.screener import lancer_scan
    if not lancer_scan():
        return jsonify({"ok": False, "message": "Scan déjà en cours"}), 429
    return jsonify({"ok": True, "message": "Scan lancé en arrière-plan"}), 202


@bp.route("/opportunites/status")
@login_required
def opportunites_status():
    _require_admin()
    from analysis.screener import get_scan_state
    return jsonify(get_scan_state())


# ── Univers de scan : suggestion IA + application (23.07.2026) ───────────

@bp.route("/opportunites/univers/suggerer", methods=["POST"])
@login_required
def opportunites_univers_suggerer():
    _require_admin()
    from analysis.screener import suggerer_univers
    prompt = (request.get_json(silent=True) or {}).get("prompt")
    if not suggerer_univers(prompt=prompt):
        return jsonify({"ok": False, "message": "Suggestion déjà en cours"}), 429
    return jsonify({"ok": True, "message": "Suggestion IA lancée en arrière-plan"}), 202


@bp.route("/opportunites/univers/status")
@login_required
def opportunites_univers_status():
    _require_admin()
    from analysis.screener import get_suggestion_state
    return jsonify(get_suggestion_state())


@bp.route("/opportunites/univers/analyser", methods=["POST"])
@login_required
def opportunites_univers_analyser():
    """
    Mode manuel : l'admin colle la réponse d'une IA (copiée-collée depuis
    son propre navigateur, jamais bloqué géographiquement contrairement à
    un appel serveur Gemini depuis Render EU). Même état/pipeline que la
    suggestion automatique.
    """
    _require_admin()
    from analysis.screener import analyser_texte_univers
    texte = (request.get_json(silent=True) or {}).get("texte")
    if not analyser_texte_univers(texte):
        return jsonify({"ok": False, "message": "Une analyse est déjà en cours"}), 429
    return jsonify({"ok": True, "message": "Analyse lancée en arrière-plan"}), 202


@bp.route("/opportunites/univers/appliquer", methods=["POST"])
@login_required
def opportunites_univers_appliquer():
    _require_admin()
    from analysis.screener import appliquer_univers, get_univers_actif
    tickers = (request.get_json(silent=True) or {}).get("tickers")
    if not isinstance(tickers, list) or not tickers:
        return jsonify({"ok": False, "error": "Liste de tickers manquante ou vide."}), 400
    try:
        appliquer_univers(tickers)
        return jsonify({"ok": True, "univers": get_univers_actif()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
