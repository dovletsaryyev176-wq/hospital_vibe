import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f'Required environment variable {name!r} is not set')
    return value


def _flag(name: str, default: bool = False) -> bool:
    """Read a boolean switch from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    SECRET_KEY = _require_env('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = _require_env('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
        'pool_timeout': 10,
    }
    WTF_CSRF_ENABLED = True

    # Session cookie. HttpOnly and SameSite cost nothing and are always on;
    # Secure is a switch, because turning it on over plain HTTP makes the
    # cookie undeliverable and nobody can log in at all. Set SESSION_COOKIE_SECURE=1
    # once the site is served over HTTPS.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = _flag('SESSION_COOKIE_SECURE')
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = _flag('SESSION_COOKIE_SECURE')
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # Nothing here is uploaded — every form is fields only, so a body larger
    # than this is a mistake or an attempt to tie the worker up.
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024

    # Set TRUST_PROXY=1 only when a reverse proxy really sits in front: it makes
    # the app believe X-Forwarded-* headers, which a direct client could forge.
    TRUST_PROXY = _flag('TRUST_PROXY')

    # Where the application log is written. Empty disables file logging and
    # leaves records on stderr.
    LOG_FILE = os.environ.get('LOG_FILE', 'logs/hospital.log')
