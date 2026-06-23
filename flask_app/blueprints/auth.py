# flask_app/blueprints/auth.py — J3 : authentification Flask-Login
# Remplace streamlit-authenticator + extra-streamlit-components.
# Conserve users.yaml + bcrypt inchangés.

import re
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from pathlib import Path
import yaml
import bcrypt

bp = Blueprint("auth", __name__, url_prefix="/auth")

USERS_FILE   = Path(__file__).parent.parent.parent / "auth" / "users.yaml"
_RE_USERNAME = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


# ── Modèle utilisateur ────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, username: str, name: str, email: str):
        self.id       = username
        self.username = username
        self.name     = name
        self.email    = email


# ── Helpers YAML ──────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(USERS_FILE) as f:
        return yaml.safe_load(f)


def _save_config(config: dict) -> None:
    with open(USERS_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


# ── Callback Flask-Login (appelé à chaque requête authentifiée) ───────────────

def load_user(username: str):
    config = _load_config()
    users  = config.get("credentials", {}).get("usernames", {})
    if username not in users:
        return None
    u = users[username]
    return User(username, u.get("name", username), u.get("email", ""))


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("stock.home"))

    errors  = {}
    prefill = {}

    if request.method == "POST":
        username    = request.form.get("username", "").strip()
        password    = request.form.get("password", "")
        remember_me = bool(request.form.get("remember_me"))
        prefill["username"] = username

        # ── Validation champs ─────────────────────────────────
        if not username:
            errors["username"] = "L'identifiant est requis."
        if not password:
            errors["password"] = "Le mot de passe est requis."

        # ── Vérification credentials ──────────────────────────
        if not errors:
            config = _load_config()
            users  = config.get("credentials", {}).get("usernames", {})
            data   = users.get(username)

            if data and bcrypt.checkpw(password.encode(), data["password"].encode()):
                user = User(username, data.get("name", username), data.get("email", ""))
                login_user(user, remember=remember_me)
                flash(f"Bienvenue, {user.name} !", "success")
                next_page = request.args.get("next") or url_for("stock.home")
                return redirect(next_page)

            errors["general"] = "Identifiant ou mot de passe incorrect."

    return render_template("auth/login.html", errors=errors, prefill=prefill)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("stock.home"))

    errors  = {}
    prefill = {}

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        name     = request.form.get("name",     "").strip()
        email    = request.form.get("email",    "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm",  "")

        prefill = {"username": username, "name": name, "email": email}

        # ── Validation ────────────────────────────────────────
        if not username:
            errors["username"] = "L'identifiant est requis."
        elif not _RE_USERNAME.match(username):
            errors["username"] = "3–32 caractères : lettres, chiffres ou _"

        if not name:
            errors["name"] = "Le nom affiché est requis."

        if not password:
            errors["password"] = "Le mot de passe est requis."
        elif len(password) < 6:
            errors["password"] = "Minimum 6 caractères."

        if password and confirm != password:
            errors["confirm"] = "Les mots de passe ne correspondent pas."

        # ── Unicité identifiant ───────────────────────────────
        if "username" not in errors:
            config = _load_config()
            users  = config.setdefault("credentials", {}).setdefault("usernames", {})
            if username in users:
                errors["username"] = "Cet identifiant est déjà pris."

        if not errors:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            users[username] = {"name": name, "email": email, "password": hashed}
            _save_config(config)
            flash("Compte créé avec succès ! Connectez-vous.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html", errors=errors, prefill=prefill)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("stock.home"))
