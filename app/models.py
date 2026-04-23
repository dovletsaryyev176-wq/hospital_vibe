from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db


class DoctorDirection(db.Model):
    __tablename__ = 'doctor_directions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f'<DoctorDirection {self.name}>'


class Analysis(db.Model):
    __tablename__ = 'analyses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    responsible_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    responsible = db.relationship('User', backref=db.backref('analyses', lazy='dynamic'))

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<Analysis {self.name}>'


class Patient(db.Model):
    __tablename__ = 'patients'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    birth_year = db.Column(db.Integer, nullable=False)
    citizenship = db.Column(db.String(100), nullable=False)
    home_address = db.Column(db.String(255), nullable=False)
    insurance_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def age(self) -> int:
        return datetime.utcnow().year - self.birth_year

    def __repr__(self) -> str:
        return f'<Patient {self.full_name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    ROLES = {
        'administrator': 'Администратор',
        'registrar': 'Регистратор',
        'doctor': 'Врач',
        'analysis_responsible': 'Ответственный по анализам',
        'cashier': 'Кассир',
    }

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    cabinet = db.Column(db.String(20), nullable=True)
    direction_id = db.Column(db.Integer, db.ForeignKey('doctor_directions.id'), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    direction = db.relationship('DoctorDirection', backref=db.backref('users', lazy='dynamic'))

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_role_display(self) -> str:
        return self.ROLES.get(self.role, self.role)

    def is_administrator(self) -> bool:
        return self.role == 'administrator'

    def __repr__(self) -> str:
        return f'<User {self.username}>'
