# flask_app/__init__.py — factory Flask

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from datetime import timedelta
from pathlib import Path
import sys
import os

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

login_manager = LoginManager()
csrf          = CSRFProtect()


def create_app() -> Flask:
    app = Flask(__name__)

    app.config["SECRET_KEY"]                 = os.getenv("FLASK_SECRET_KEY", "changez_moi_en_production")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["SESSION_COOKIE_HTTPONLY"]    = True
    app.config["SESSION_COOKIE_SAMESITE"]    = "Lax"
    app.config["WTF_CSRF_TIME_LIMIT"]       = None

    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view             = "auth.login"
    login_manager.login_message          = "Connectez-vous pour accéder à cette page."
    login_manager.login_message_category = "warning"

    from flask_app.blueprints.auth import load_user as _load_user
    login_manager.user_loader(_load_user)

    from flask_app.blueprints.auth      import bp as auth_bp
    from flask_app.blueprints.stock     import bp as stock_bp
    from flask_app.blueprints.cron      import bp as cron_bp
    from flask_app.blueprints.portfolio import bp as portfolio_bp
    from flask_app.blueprints.admin     import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(admin_bp)
    csrf.exempt(cron_bp)          # pas de token CSRF — le blueprint a son propre secret
    app.register_blueprint(cron_bp)

    _admin_emails = set(e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip())

    @app.context_processor
    def inject_admin():
        return {"admin_emails": _admin_emails}

    # Handlers d'erreurs personnalisés
    from flask import render_template as _rt

    @app.errorhandler(404)
    def page_not_found(e):
        return _rt("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        return _rt("errors/500.html"), 500

    @app.errorhandler(403)
    def forbidden(e):
        return _rt("errors/403.html"), 403

    return app
