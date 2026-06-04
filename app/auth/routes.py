from urllib.parse import urlparse
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from app.auth import auth_bp
from app.auth.forms import AdminLoginForm, LoginForm
from app.models import User


def _safe_next(next_url: str | None, fallback: str) -> str:
    if next_url:
        parsed = urlparse(next_url)
        if not parsed.netloc and not parsed.scheme:
            return next_url
    return fallback


# ── Admin login ───────────────────────────────────────────────────────────────

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_administrator():
        return redirect(url_for('admin.dashboard'))

    form = AdminLoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()

        if user is None or not user.check_password(form.password.data):
            flash('Nädogry ulanyjy ady ýa-da gizlin belgisi.', 'danger')
            return render_template('auth/admin_login.html', form=form)

        if not user.is_administrator():
            flash('Dolandyryjy paneline girmek gadagan.', 'danger')
            return render_template('auth/admin_login.html', form=form)

        if not user.is_active:
            flash('Siziň ulanyjyňyz bloklanan.', 'danger')
            return render_template('auth/admin_login.html', form=form)

        login_user(user, remember=form.remember_me.data)
        return redirect(_safe_next(request.args.get('next'), url_for('admin.dashboard')))

    return render_template('auth/admin_login.html', form=form)


@auth_bp.route('/admin/logout')
def admin_logout():
    logout_user()
    flash('Siz ulgamdan çykdyňyz.', 'info')
    return redirect(url_for('auth.admin_login'))


# ── Main login ────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and not current_user.is_administrator():
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()

        if user is None or not user.check_password(form.password.data):
            flash('Nädogry ulanyjy ady ýa-da gizlin belgisi.', 'danger')
            return render_template('auth/login.html', form=form)

        if user.is_administrator():
            flash('Dolandyryjy paneline girmek üçin beýleki penjirä geçiň.', 'warning')
            return render_template('auth/login.html', form=form)

        if not user.is_active:
            flash('Siziň ulanyjyňyz bloklanan.', 'danger')
            return render_template('auth/login.html', form=form)

        login_user(user, remember=form.remember_me.data)
        return redirect(_safe_next(request.args.get('next'), url_for('main.dashboard')))

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
def logout():
    logout_user()
    flash('Siz ulgamdan çykdyňyz.', 'info')
    return redirect(url_for('auth.login'))
