# flask_app/__init__.py — factory Flask

from flask import Flask
from flask_login import LoginManager
from pathlib import Path
import sys

# Chemin racine du projet pour les imports pipeline/data/analysis
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

login_manager = LoginManager()


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Config ────────────────────────────────────────────────
    app.config["SECRET_KEY"] = "stockengine_secret_key_changez_moi"
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = str(ROOT / ".flask_sessions")

    # ── Flask-Login ───────────────────────────────────────────
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Connectez-vous pour accéder à cette page."
    login_manager.login_message_category = "warning"

    # user_loader doit être enregistré après init_app
    from flask_app.blueprints.auth import load_user as _load_user
    login_manager.user_loader(_load_user)

    # ── Blueprints ────────────────────────────────────────────
    from flask_app.blueprints.auth import bp as auth_bp
    from flask_app.blueprints.stock import bp as stock_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(stock_bp)

    return app
