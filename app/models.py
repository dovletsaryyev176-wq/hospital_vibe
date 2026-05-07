from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db


class PricingSnapshotMixin:
    """Shared pricing logic for ExaminationAnalysis and ExaminationDirection.

    Subclasses must expose: self.price, self.is_insurance, self.examination, self._source
    where _source is the catalogue object (Analysis or DoctorDirection).
    """

    @property
    def snapshot_price(self):
        return self.price if self.price is not None else self._source.price

    @property
    def snapshot_is_insurance(self):
        return self.is_insurance if self.is_insurance is not None else self._source.is_insurance

    @property
    def effective_price(self):
        has_ins = bool(self.examination.patient_has_insurance)
        return self.snapshot_price / 2 if (has_ins and self.snapshot_is_insurance) else self.snapshot_price

    @property
    def snapshot_price_display(self):
        return f'{self.snapshot_price:,.2f}'

    @property
    def effective_price_display(self):
        return f'{self.effective_price:,.2f}'


class DoctorDirection(db.Model):
    __tablename__ = 'doctor_directions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @property
    def price_display(self):
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<DoctorDirection {self.name}>'


class Analysis(db.Model):
    __tablename__ = 'analyses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    responsible_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    responsible = db.relationship('User', backref=db.backref('analyses', lazy='dynamic'))

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<Analysis {self.name}>'


combined_analysis_items = db.Table(
    'combined_analysis_items',
    db.Column('combined_analysis_id', db.Integer, db.ForeignKey('combined_analyses.id'), primary_key=True),
    db.Column('analysis_id', db.Integer, db.ForeignKey('analyses.id'), primary_key=True),
)


class CombinedAnalysis(db.Model):
    __tablename__ = 'combined_analyses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    analyses = db.relationship(
        'Analysis', secondary=combined_analysis_items, lazy='subquery',
        backref=db.backref('combined_analyses', lazy='dynamic'),
    )

    @property
    def total_price(self):
        return sum(a.price for a in self.analyses)

    @property
    def price_display(self) -> str:
        return f'{self.total_price:,.2f}'

    def __repr__(self) -> str:
        return f'<CombinedAnalysis {self.name}>'


class Patient(db.Model):
    __tablename__ = 'patients'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    birth_year = db.Column(db.Integer, nullable=False)
    citizenship = db.Column(db.String(100), nullable=False)
    home_address = db.Column(db.String(255), nullable=False)
    passport_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    insurance_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @property
    def age(self) -> int:
        return datetime.now().year - self.birth_year

    def __repr__(self) -> str:
        return f'<Patient {self.full_name}>'


user_directions = db.Table(
    'user_directions',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('direction_id', db.Integer, db.ForeignKey('doctor_directions.id'), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    ROLES = {
        'administrator': 'Dolandyryjy',
        'registrar': 'Kabulhana',
        'doctor': 'Lukman',
        'analysis_responsible': 'Analizler boýunça jogapkär',
        'cashier': 'Kassir',
    }

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    cabinet = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    directions = db.relationship('DoctorDirection', secondary=user_directions, lazy='select',
                                 backref=db.backref('users', lazy='dynamic'))

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


class Examination(db.Model):
    __tablename__ = 'examinations'

    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open')
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    is_paid = db.Column(db.Boolean, default=False, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    paid_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    patient_has_insurance = db.Column(db.Boolean, default=False, nullable=True)

    patient = db.relationship('Patient', backref=db.backref('examinations', lazy='dynamic'))
    created_by = db.relationship('User', foreign_keys=[created_by_id],
                                 backref=db.backref('created_examinations', lazy='dynamic'))
    paid_by = db.relationship('User', foreign_keys=[paid_by_id])
    exam_analyses = db.relationship('ExaminationAnalysis', back_populates='examination',
                                    cascade='all, delete-orphan')
    exam_directions = db.relationship('ExaminationDirection', back_populates='examination',
                                      cascade='all, delete-orphan')

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

    def __repr__(self) -> str:
        return f'<Examination {self.id}>'


class ExaminationAnalysis(PricingSnapshotMixin, db.Model):
    __tablename__ = 'examination_analyses'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analyses.id'), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    is_submitted = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_analyses')
    analysis = db.relationship('Analysis')
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id])

    @property
    def _source(self):
        return self.analysis


class ExaminationDirection(PricingSnapshotMixin, db.Model):
    __tablename__ = 'examination_directions'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey('doctor_directions.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    is_visited = db.Column(db.Boolean, default=False, nullable=False)
    visited_at = db.Column(db.DateTime, nullable=True)

    examination = db.relationship('Examination', back_populates='exam_directions')
    direction = db.relationship('DoctorDirection')
    doctor = db.relationship('User', foreign_keys=[doctor_id])

    @property
    def _source(self):
        return self.direction
