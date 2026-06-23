# flask_app/blueprints/auth.py — J3 : authentification Flask-Login
# Remplace streamlit-authenticator + extra-streamlit-components.
# Conserve users.yaml + bcrypt inchangés.

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from pathlib import Path
import yaml
import bcrypt

bp = Blueprint("auth", __name__, url_prefix="/auth")

USERS_FILE = Path(__file__).parent.parent.parent / "auth" / "users.yaml"


# ── Modèle utilisateur ────────────────────────────────────────────────────────

class User(UserMixin):
    """Représente un utilisateur chargé depuis users.yaml."""

    def __init__(self, username: str, name: str, email: str):
        self.id = username          # Flask-Login utilise .id comme clé de session
        self.username = username
        self.name = name
        self.email = email


# ── Helpers YAML ──────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(USERS_FILE) as f:
        return yaml.safe_load(f)


def _save_config(config: dict) -> None:
    with open(USERS_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


# ── Callback Flask-Login ──────────────────────────────────────────────────────

def load_user(username: str):
    """Reconstruit un User depuis la session — appelé par Flask-Login à chaque requête."""
    config = _load_config()
    users = config.get("credentials", {}).get("usernames", {})
    if username not in users:
        return None
    u = users[username]
    return User(username, u.get("name", username), u.get("email", ""))


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("stock.home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        config   = _load_config()
        users    = config.get("credentials", {}).get("usernames", {})
        data     = users.get(username)

        if data and bcrypt.checkpw(password.encode(), data["password"].encode()):
            user = User(username, data.get("name", username), data.get("email", ""))
            login_user(user, remember=True)
            flash(f"Bienvenue, {user.name} !", "success")
            next_page = request.args.get("next") or url_for("stock.home")
            return redirect(next_page)

        flash("Identifiant ou mot de passe incorrect.", "danger")

    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("stock.home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "warning")
            return render_template("auth/register.html")

        config = _load_config()
        users  = config.setdefault("credentials", {}).setdefault("usernames", {})

        if username in users:
            flash("Cet identifiant est déjà pris.", "warning")
            return render_template("auth/register.html")

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        users[username] = {"name": name, "email": email, "password": hashed}
        _save_config(config)

        flash("Compte créé avec succès ! Vous pouvez vous connecter.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("stock.home"))
