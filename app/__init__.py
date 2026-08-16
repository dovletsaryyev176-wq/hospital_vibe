from flask import Flask, redirect, url_for
from flask_login import current_user
from config import Config
from app.extensions import db, login_manager, migrate, csrf


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Default redirect for @login_required — main users land on main login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Войдите в систему для доступа.'
    login_manager.login_message_category = 'warning'

    from app.models import User

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
