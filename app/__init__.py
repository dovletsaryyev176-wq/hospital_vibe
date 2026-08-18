import logging
import os
from logging.handlers import RotatingFileHandler
from flask import Flask, redirect, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from app.extensions import db, login_manager, migrate, csrf


def _configure_logging(app):
    """Keep a rolling application log.

    A 500 that only ever reached the console is a 500 nobody can look into
    afterwards, and this runs unattended under waitress.
    """
    log_file = app.config.get('LOG_FILE')
    if not log_file:
        return
    directory = os.path.dirname(os.path.abspath(log_file))
    os.makedirs(directory, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024,
                                  backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s: %(message)s'))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if app.config.get('TRUST_PROXY'):
        # Only with a reverse proxy actually in front — see config.TRUST_PROXY.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _configure_logging(app)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Default redirect for @login_required — main users land on main login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Войдите в систему для доступа.'
    login_manager.login_message_category = 'warning'

    from app.models import User, format_quantity

    # drug amounts must read as «10» / «0.5», never «10.00» — used wherever a
    # stock remainder is printed
    app.jinja_env.filters['quantity'] = format_quantity

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from app.main import main_bp
    app.register_blueprint(main_bp, url_prefix='/app')

    from app.inpatient import inpatient_bp
    app.register_blueprint(inpatient_bp, url_prefix='/stasionar')

    from app.commands import create_admin
    app.cli.add_command(create_admin)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.is_administrator():
                return redirect(url_for('admin.dashboard'))
            if current_user.is_inpatient_only():
                return redirect(url_for('inpatient.dashboard'))
            return redirect(url_for('main.dashboard'))
        return redirect(url_for('auth.login'))

    return app
