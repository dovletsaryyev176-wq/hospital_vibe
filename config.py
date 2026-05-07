import os
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f'Required environment variable {name!r} is not set')
    return value


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
