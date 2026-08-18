import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from urllib.parse import urlparse
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, current_user
from app.auth import auth_bp
from app.auth.forms import AdminLoginForm, LoginForm
from app.models import User


# ── Login throttle ────────────────────────────────────────────────────────────
#
# Without this a password can be guessed at the speed of the network. Failures
# are counted per (username, client address) so one attacker cannot lock a real
# member of staff out by hammering their name from elsewhere. The state is kept
# in the process — the app runs as a single waitress instance, and losing the
# counters on restart only costs an attacker's progress, never a user's access.

LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_MAX_FAILURES = 8

_login_failures = defaultdict(deque)
_login_lock = threading.Lock()


def _throttle_key(username: str) -> tuple:
    return ((username or '').strip().lower(), request.remote_addr or '-')


def _prune(bucket, now):
    while bucket and now - bucket[0] > LOGIN_WINDOW:
        bucket.popleft()


def login_blocked(username: str) -> bool:
    """Whether this name/address pair has spent its attempts for now."""
    now = datetime.now()
    with _login_lock:
        bucket = _login_failures.get(_throttle_key(username))
        if bucket is None:
            return False
        _prune(bucket, now)
        return len(bucket) >= LOGIN_MAX_FAILURES


def note_login_failure(username: str) -> None:
    now = datetime.now()
    key = _throttle_key(username)
    with _login_lock:
        bucket = _login_failures[key]
        _prune(bucket, now)
        bucket.append(now)
        # keep the table from growing without bound as names are tried
        if len(_login_failures) > 2048:
            for stale_key, stale in list(_login_failures.items()):
                _prune(stale, now)
                if not stale:
                    del _login_failures[stale_key]
    current_app.logger.warning(
        'Failed login for %r from %s', key[0], key[1])


def clear_login_failures(username: str) -> None:
    with _login_lock:
        _login_failures.pop(_throttle_key(username), None)


THROTTLE_MESSAGE = 'Örän köp synanyşyk. 15 minutdan soň gaýtadan synanyşyň.'


def _landing_page(user) -> str:
    """Where a non-admin user lands after logging in."""
    if user.is_inpatient_only():
        return url_for('inpatient.dashboard')
    return url_for('main.dashboard')


def _safe_next(next_url: str | None, fallback: str) -> str:
    """Only follow a relative in-app path — never an absolute / protocol-relative
    URL. Backslashes are rejected too: some browsers treat them as slashes,
    which would turn e.g. '/\\evil.com' into '//evil.com'."""
    if next_url and '\\' not in next_url:
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
        username = form.username.data.strip()

        if login_blocked(username):
            flash(THROTTLE_MESSAGE, 'danger')
            return render_template('auth/admin_login.html', form=form)

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(form.password.data):
            note_login_failure(username)
            flash('Nädogry ulanyjy ady ýa-da gizlin belgisi.', 'danger')
            return render_template('auth/admin_login.html', form=form)

        if not user.is_administrator():
            flash('Dolandyryjy paneline girmek gadagan.', 'danger')
            return render_template('auth/admin_login.html', form=form)

        if not user.is_active:
            flash('Siziň ulanyjyňyz bloklanan.', 'danger')
            return render_template('auth/admin_login.html', form=form)

        clear_login_failures(username)
        login_user(user, remember=form.remember_me.data)
        return redirect(_safe_next(request.args.get('next'), url_for('admin.dashboard')))

    return render_template('auth/admin_login.html', form=form)


@auth_bp.route('/admin/logout', methods=['POST'])
def admin_logout():
    logout_user()
    flash('Siz ulgamdan çykdyňyz.', 'info')
    return redirect(url_for('auth.admin_login'))


# ── Main login ────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and not current_user.is_administrator():
        return redirect(_landing_page(current_user))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()

        if login_blocked(username):
            flash(THROTTLE_MESSAGE, 'danger')
            return render_template('auth/login.html', form=form)

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(form.password.data):
            note_login_failure(username)
            flash('Nädogry ulanyjy ady ýa-da gizlin belgisi.', 'danger')
            return render_template('auth/login.html', form=form)

        if user.is_administrator():
            flash('Dolandyryjy paneline girmek üçin beýleki penjirä geçiň.', 'warning')
            return render_template('auth/login.html', form=form)

        if not user.is_active:
            flash('Siziň ulanyjyňyz bloklanan.', 'danger')
            return render_template('auth/login.html', form=form)

        clear_login_failures(username)
        login_user(user, remember=form.remember_me.data)
        return redirect(_safe_next(request.args.get('next'), _landing_page(user)))

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    logout_user()
    flash('Siz ulgamdan çykdyňyz.', 'info')
    return redirect(url_for('auth.login'))
