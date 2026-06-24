# flask_app/blueprints/auth.py
# Auth Flask-Login — stockage MongoDB (si MONGO_URI défini) ou YAML local (dev)

import re
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from pathlib import Path
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


# ── Backends de stockage ──────────────────────────────────────────────────────

def _db_ok() -> bool:
    try:
        from db import is_available
        return is_available()
    except Exception:
        return False


def _yaml_load() -> dict:
    import yaml
    if not USERS_FILE.exists():
        return {"credentials": {"usernames": {}}}
    with open(USERS_FILE) as f:
        return yaml.safe_load(f) or {"credentials": {"usernames": {}}}


def _yaml_save(config: dict) -> None:
    import yaml
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def _find_user(username: str) -> dict | None:
    """Cherche un utilisateur par username. Retourne un dict ou None."""
    if _db_ok():
        try:
            from db import find_one
            return find_one("users", {"username": username}, {"_id": 0})
        except Exception:
            pass
    # Fallback YAML
    config = _yaml_load()
    data   = config.get("credentials", {}).get("usernames", {}).get(username)
    if data:
        return {"username": username, "name": data.get("name", username),
                "email": data.get("email", ""), "password": data["password"]}
    return None


def _create_user(username: str, name: str, email: str, hashed: str) -> None:
    """Crée un utilisateur."""
    if _db_ok():
        try:
            from db import insert_one
            insert_one("users", {"username": username, "name": name,
                                 "email": email, "password": hashed})
            return
        except Exception:
            pass
    # Fallback YAML
    config = _yaml_load()
    config.setdefault("credentials", {}).setdefault("usernames", {})[username] = {
        "name": name, "email": email, "password": hashed,
    }
    _yaml_save(config)


def _username_exists(username: str) -> bool:
    if _db_ok():
        try:
            from db import count_documents
            return count_documents("users", {"username": username}) > 0
        except Exception:
            pass
    config = _yaml_load()
    return username in config.get("credentials", {}).get("usernames", {})


# ── Callback Flask-Login ──────────────────────────────────────────────────────

def load_user(username: str):
    data = _find_user(username)
    if not data:
        return None
    return User(data["username"], data.get("name", username), data.get("email", ""))


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

        if not username:
            errors["username"] = "L'identifiant est requis."
        if not password:
            errors["password"] = "Le mot de passe est requis."

        if not errors:
            data = _find_user(username)
            if data and bcrypt.checkpw(password.encode(), data["password"].encode()):
                user = User(data["username"], data.get("name", username), data.get("email", ""))
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

        if "username" not in errors and _username_exists(username):
            errors["username"] = "Cet identifiant est déjà pris."

        if not errors:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            _create_user(username, name, email, hashed)
            flash("Compte créé avec succès ! Connectez-vous.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html", errors=errors, prefill=prefill)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("stock.home"))
