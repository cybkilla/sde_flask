# flask_app/blueprints/profile.py — Page de profil utilisateur

import bcrypt
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

bp = Blueprint("profile", __name__, url_prefix="/profile")

_MAX_AVATAR_BYTES = 80_000   # ~80 Ko max (base64 d'une image 128×128)


def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def _update_field(username: str, fields: dict) -> bool:
    if _db_ok():
        try:
            from db import update_one
            update_one("users", {"username": username}, {"$set": fields})
            return True
        except Exception:
            pass
    return False


def _get_user_row(username: str) -> dict:
    try:
        from db import find_one
        return find_one("users", {"username": username}) or {}
    except Exception:
        return {}


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
def page():
    row = _get_user_row(current_user.id)
    return render_template("profile.html", user_row=row)


@bp.route("/info", methods=["POST"])
@login_required
def update_info():
    data  = request.get_json(silent=True) or {}
    name  = data.get("name",  "").strip()
    email = data.get("email", "").strip().lower()

    if not name:
        return jsonify({"ok": False, "error": "Le nom ne peut pas être vide"}), 400

    fields = {"name": name}
    if email:
        fields["email"] = email

    if _update_field(current_user.id, fields):
        # Mettre à jour le nom sur l'objet courant (sans re-login)
        current_user.name  = name
        if email:
            current_user.email = email
        return jsonify({"ok": True, "name": name})
    return jsonify({"ok": False, "error": "Erreur de mise à jour"}), 500


@bp.route("/password", methods=["POST"])
@login_required
def update_password():
    data        = request.get_json(silent=True) or {}
    current_pwd = data.get("current",  "")
    new_pwd     = data.get("password", "")
    confirm     = data.get("confirm",  "")

    if not current_pwd or not new_pwd:
        return jsonify({"ok": False, "error": "Tous les champs sont requis"}), 400

    # Vérifier le mot de passe actuel
    row = _get_user_row(current_user.id)
    if not row or not bcrypt.checkpw(current_pwd.encode(), row["password"].encode()):
        return jsonify({"ok": False, "error": "Mot de passe actuel incorrect"}), 403

    if new_pwd != confirm:
        return jsonify({"ok": False, "error": "Les nouveaux mots de passe ne correspondent pas"}), 400

    from auth.password_policy import validate as _pw_validate
    errors = _pw_validate(new_pwd)
    if errors:
        return jsonify({"ok": False, "error": " · ".join(errors)}), 400

    hashed = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt()).decode()
    if _update_field(current_user.id, {"password": hashed}):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Erreur de mise à jour"}), 500


@bp.route("/avatar", methods=["POST"])
@login_required
def upload_avatar():
    data   = request.get_json(silent=True) or {}
    avatar = data.get("avatar", "")

    if not avatar.startswith("data:image/"):
        return jsonify({"ok": False, "error": "Format d'image invalide"}), 400
    if len(avatar.encode()) > _MAX_AVATAR_BYTES:
        return jsonify({"ok": False, "error": "Image trop lourde (max 80 Ko)"}), 400

    if _update_field(current_user.id, {"avatar": avatar}):
        current_user.avatar = avatar
        return jsonify({"ok": True, "avatar": avatar})
    return jsonify({"ok": False, "error": "Erreur de sauvegarde"}), 500


@bp.route("/avatar", methods=["DELETE"])
@login_required
def delete_avatar():
    if _update_field(current_user.id, {"avatar": ""}):
        current_user.avatar = ""
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Erreur de suppression"}), 500
