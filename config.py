import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'mysql+pymysql://root:password@localhost/hospital_vibe'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,   # проверяет соединение перед использованием, убирает мёртвые
        'pool_recycle': 300,     # пересоздаёт соединения каждые 5 минут
        'pool_size': 10,         # базовый размер пула
        'max_overflow': 20,      # дополнительные соединения при пике нагрузки
        'pool_timeout': 10,      # не ждать дольше 10 сек — быстрее падать с ошибкой
    }
    WTF_CSRF_ENABLED = True
