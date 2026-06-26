# flask_app/blueprints/auth.py
# Auth Flask-Login — stockage Supabase (si SUPABASE_URL défini) ou YAML local (dev)

import re
from collections import defaultdict
from time import time
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from pathlib import Path
import bcrypt

bp = Blueprint("auth", __name__, url_prefix="/auth")

USERS_FILE   = Path(__file__).parent.parent.parent / "auth" / "users.yaml"
_RE_USERNAME = re.compile(r"^[a-zA-Z0-9_]{3,32}$")

# ── Rate limiting login (in-memory, adapté au worker unique Gunicorn) ────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS   = 5
_WINDOW_SEC     = 15 * 60   # 15 minutes


def _rate_ok(ip: str) -> bool:
    now  = time()
    hits = [t for t in _login_attempts[ip] if now - t < _WINDOW_SEC]
    _login_attempts[ip] = hits
    return len(hits) < _MAX_ATTEMPTS


def _rate_hit(ip: str):
    _login_attempts[ip].append(time())


# ── Modèle utilisateur ────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, username: str, name: str, email: str, avatar: str = ""):
        self.id       = username
        self.username = username
        self.name     = name
        self.email    = email
        self.avatar   = avatar


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
    if _db_ok():
        try:
            from db import find_one
            result = find_one("users", {"username": username}, {"_id": 0})
            if result:
                return result
        except Exception:
            pass
    config = _yaml_load()
    data   = config.get("credentials", {}).get("usernames", {}).get(username)
    if data:
        return {"username": username, "name": data.get("name", username),
                "email": data.get("email", ""), "password": data["password"],
                "email_verified": True}
    return None


def _find_user_by_email(email: str) -> dict | None:
    if not email:
        return None
    if _db_ok():
        try:
            from db import find_one
            return find_one("users", {"email": email})
        except Exception:
            pass
    config = _yaml_load()
    for uname, data in config.get("credentials", {}).get("usernames", {}).items():
        if data.get("email", "").lower() == email.lower():
            return {"username": uname, **data}
    return None


def _create_user(username: str, name: str, email: str, hashed: str,
                 email_verified: bool = True) -> None:
    if _db_ok():
        try:
            from db import insert_one
            insert_one("users", {"username": username, "name": name,
                                 "email": email, "password": hashed,
                                 "email_verified": email_verified})
            return
        except Exception:
            pass
    config = _yaml_load()
    config.setdefault("credentials", {}).setdefault("usernames", {})[username] = {
        "name": name, "email": email, "password": hashed,
    }
    _yaml_save(config)


def _update_password(username: str, hashed: str) -> bool:
    if _db_ok():
        try:
            from db import update_one
            update_one("users", {"username": username}, {"$set": {"password": hashed}})
            return True
        except Exception:
            pass
    config = _yaml_load()
    users  = config.get("credentials", {}).get("usernames", {})
    if username not in users:
        return False
    users[username]["password"] = hashed
    _yaml_save(config)
    return True


def _activate_user(username: str) -> None:
    if _db_ok():
        try:
            from db import update_one
            update_one("users", {"username": username},
                       {"$set": {"email_verified": True}})
            return
        except Exception:
            pass
    # YAML : pas de colonne email_verified → compte toujours actif


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
    return User(data["username"], data.get("name", username),
                data.get("email", ""), data.get("avatar", ""))


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("stock.home"))

    errors  = {}
    prefill = {"username": request.args.get("username", "")}

    if request.method == "POST":
        username    = request.form.get("username", "").strip()
        password    = request.form.get("password", "")
        remember_me = bool(request.form.get("remember_me"))
        prefill["username"] = username
        ip = request.remote_addr or "unknown"

        if not username:
            errors["username"] = "L'identifiant est requis."
        if not password:
            errors["password"] = "Le mot de passe est requis."

        if not errors:
            if not _rate_ok(ip):
                errors["general"] = (
                    "Trop de tentatives. Réessayez dans 15 minutes."
                )
            else:
                _rate_hit(ip)
                data = _find_user(username)
                if data and bcrypt.checkpw(password.encode(), data["password"].encode()):
                    # Vérification compte activé
                    if data.get("email_verified") is False:
                        errors["general"] = (
                            "Compte non activé. Vérifiez vos emails "
                            "(y compris les spams)."
                        )
                    else:
                        user = User(data["username"], data.get("name", username),
                                    data.get("email", ""))
                        login_user(user, remember=remember_me)
                        flash(f"Bienvenue, {user.name} !", "success")
                        next_page = request.args.get("next", "")
                        parsed = urlparse(urljoin(request.host_url, next_page))
                        if not next_page or parsed.netloc != urlparse(request.host_url).netloc:
                            next_page = url_for("stock.home")
                        return redirect(next_page)
                else:
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
        email    = request.form.get("email",    "").strip().lower()
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
        else:
            from auth.password_policy import validate as _pw_validate
            pw_errors = _pw_validate(password)
            if pw_errors:
                errors["password"] = " · ".join(pw_errors)

        if password and not errors.get("password") and confirm != password:
            errors["confirm"] = "Les mots de passe ne correspondent pas."

        if "username" not in errors and _username_exists(username):
            errors["username"] = "Cet identifiant est déjà pris."

        if not errors:
            needs_activation = bool(email)
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            _create_user(username, name, email, hashed,
                         email_verified=not needs_activation)

            if needs_activation:
                try:
                    from auth.auth_tokens import generate, send_activation
                    token = generate(username, "activation", hours=24)
                    if token:
                        send_activation(email, username, token)
                except Exception as e:
                    print(f"[Auth] activation email erreur : {e}", flush=True)
                flash(
                    "Compte créé ! Un email d'activation vous a été envoyé. "
                    "Vérifiez vos spams si besoin.",
                    "info"
                )
            else:
                flash("Compte créé avec succès ! Connectez-vous.", "success")

            return redirect(url_for("auth.login"))

    return render_template("auth/register.html", errors=errors, prefill=prefill)


@bp.route("/activate/<token>")
def activate(token: str):
    from auth.auth_tokens import validate, consume
    username = validate(token, "activation")
    if not username:
        flash("Lien d'activation invalide ou expiré.", "danger")
        return redirect(url_for("auth.login"))
    _activate_user(username)
    consume(token)
    flash("Compte activé ! Vous pouvez maintenant vous connecter.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("stock.home"))
    sent = False
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if email:
            user = _find_user_by_email(email)
            if user:
                try:
                    from auth.auth_tokens import generate, send_reset
                    token = generate(user["username"], "reset", hours=1)
                    if token:
                        send_reset(email, user["username"], token)
                except Exception as e:
                    print(f"[Auth] reset email erreur : {e}", flush=True)
        # Toujours afficher le message (pas de fuite d'info sur l'existence du compte)
        sent = True
    return render_template("auth/forgot_password.html", sent=sent)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    from auth.auth_tokens import validate, consume
    username = validate(token, "reset")
    if not username:
        flash("Lien de réinitialisation invalide ou expiré.", "danger")
        return redirect(url_for("auth.forgot_password"))

    errors = {}
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm",  "")

        from auth.password_policy import validate as _pw_validate
        pw_errors = _pw_validate(password)
        if pw_errors:
            errors["password"] = " · ".join(pw_errors)
        elif confirm != password:
            errors["confirm"] = "Les mots de passe ne correspondent pas."

        if not errors:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            _update_password(username, hashed)
            consume(token)
            flash("Mot de passe modifié avec succès ! Connectez-vous.", "success")
            return redirect(url_for("auth.login", username=username))

    return render_template("auth/reset_password.html", token=token, errors=errors)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("stock.home"))
