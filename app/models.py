from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db


class PricingSnapshotMixin:
    """Shared pricing logic for ExaminationAnalysis and ExaminationDirection.

    Subclasses must expose: self.price, self.is_insurance, self.examination, self._source
    where _source is the catalogue object (Analysis or DoctorDirection).
    """

    PAYMENT_CASH = 'cash'
    PAYMENT_TERMINAL = 'terminal'
    PAYMENT_METHODS = (PAYMENT_CASH, PAYMENT_TERMINAL)

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

    @property
    def effective_total(self):
        qty = getattr(self, 'quantity', 1) or 1
        return self.effective_price * qty

    @property
    def effective_total_display(self):
        return f'{self.effective_total:,.2f}'

    @property
    def snapshot_total(self):
        qty = getattr(self, 'quantity', 1) or 1
        return self.snapshot_price * qty

    @property
    def snapshot_total_display(self):
        return f'{self.snapshot_total:,.2f}'


direction_analyses = db.Table(
    'direction_analyses',
    db.Column('direction_id', db.Integer, db.ForeignKey('doctor_directions.id'), primary_key=True),
    db.Column('analysis_id', db.Integer, db.ForeignKey('analyses.id'), primary_key=True),
)


class DoctorDirectionCategory(db.Model):
    __tablename__ = 'doctor_direction_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    directions = db.relationship('DoctorDirection', back_populates='category', lazy='dynamic')

    def __repr__(self) -> str:
        return f'<DoctorDirectionCategory {self.name}>'


class DoctorDirection(db.Model):
    __tablename__ = 'doctor_directions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('doctor_direction_categories.id'), nullable=True)

    analyses = db.relationship(
        'Analysis', secondary=direction_analyses, lazy='subquery',
        backref=db.backref('directions', lazy='dynamic'),
    )
    category = db.relationship('DoctorDirectionCategory', back_populates='directions')

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


user_departments = db.Table(
    'user_departments',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('department_id', db.Integer, db.ForeignKey('departments.id'), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    ROLES = {
        'administrator': 'Dolandyryjy',
        'registrar': 'Kabulhana',
        'doctor': 'Lukman',
        'analysis_responsible': 'Analizler boýunça jogapkär',
        'cashier': 'Kassir',
        'senior_cashier': 'Uly kassir',
        'department_head': 'Bölüm müdiri',
        'senior_nurse': 'Uly şepagat uýasy',
        'nurse': 'Şepagat uýasy',
    }

    # Roles that may be attached to inpatient departments (ýatymlaýyn bölümler)
    DEPARTMENT_ROLES = ('department_head', 'senior_nurse', 'nurse', 'doctor')

    # Roles allowed into the inpatient section
    INPATIENT_ROLES = ('doctor', 'department_head', 'senior_nurse', 'nurse')

    # Of those, the ones that work *only* in the inpatient section — they land
    # there after login instead of the outpatient (main) section
    INPATIENT_ONLY_ROLES = ('department_head', 'senior_nurse', 'nurse')

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
    departments = db.relationship('Department', secondary=user_departments, lazy='select',
                                  backref=db.backref('users', lazy='dynamic'))

    def can_have_departments(self) -> bool:
        """Whether departments may be assigned to this user (inpatient module)."""
        return self.role in self.DEPARTMENT_ROLES

    def can_access_inpatient(self) -> bool:
        return self.role in self.INPATIENT_ROLES

    def is_inpatient_only(self) -> bool:
        """User works in the inpatient section only — no outpatient access."""
        return self.role in self.INPATIENT_ONLY_ROLES

    @property
    def active_departments(self):
        """Departments assigned to this user, blocked ones excluded."""
        return [d for d in self.departments if d.is_active]

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
    exam_tools = db.relationship('ExaminationAnalysisTool', back_populates='examination',
                                 cascade='all, delete-orphan')
    exam_blanks = db.relationship('ExaminationBlank', back_populates='examination',
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
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)
    is_submitted = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_analyses')
    analysis = db.relationship('Analysis')
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id])

    @property
    def _source(self):
        return self.analysis


class ExaminationAnalysisTool(PricingSnapshotMixin, db.Model):
    __tablename__ = 'examination_analysis_tools'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    tool_id = db.Column(db.Integer, db.ForeignKey('analysis_tools.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_tools')
    tool = db.relationship('AnalysisTool')

    @property
    def _source(self):
        return self.tool


analysis_tool_analyses = db.Table(
    'analysis_tool_analyses',
    db.Column('tool_id', db.Integer, db.ForeignKey('analysis_tools.id'), primary_key=True),
    db.Column('analysis_id', db.Integer, db.ForeignKey('analyses.id'), primary_key=True),
)


class AnalysisToolCategory(db.Model):
    __tablename__ = 'analysis_tool_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    subcategories = db.relationship('AnalysisToolSubcategory', back_populates='category', lazy='dynamic')

    def __repr__(self) -> str:
        return f'<AnalysisToolCategory {self.name}>'


class AnalysisToolSubcategory(db.Model):
    __tablename__ = 'analysis_tool_subcategories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('analysis_tool_categories.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    category = db.relationship('AnalysisToolCategory', back_populates='subcategories')

    def __repr__(self) -> str:
        return f'<AnalysisToolSubcategory {self.name}>'


class AnalysisTool(db.Model):
    __tablename__ = 'analysis_tools'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('analysis_tool_categories.id'), nullable=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('analysis_tool_subcategories.id'), nullable=True)

    analyses = db.relationship(
        'Analysis', secondary=analysis_tool_analyses, lazy='subquery',
        backref=db.backref('tools', lazy='dynamic'),
    )
    category = db.relationship('AnalysisToolCategory')
    subcategory = db.relationship('AnalysisToolSubcategory')

    @property
    def analysis(self):
        return self.analyses[0] if self.analyses else None

    @property
    def price(self):
        return self.total_price

    @property
    def total_price_display(self) -> str:
        return f'{self.total_price:,.2f}'

    def __repr__(self) -> str:
        return f'<AnalysisTool {self.name}>'


blank_analyses = db.Table(
    'blank_analyses',
    db.Column('blank_id', db.Integer, db.ForeignKey('blanks.id'), primary_key=True),
    db.Column('analysis_id', db.Integer, db.ForeignKey('analyses.id'), primary_key=True),
)


class Blank(db.Model):
    __tablename__ = 'blanks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    analyses = db.relationship(
        'Analysis', secondary=blank_analyses, lazy='subquery',
        backref=db.backref('blanks', lazy='dynamic'),
    )

    @property
    def analysis(self):
        return self.analyses[0] if self.analyses else None

    @property
    def price(self):
        return self.total_price

    @property
    def total_price_display(self) -> str:
        return f'{self.total_price:,.2f}'

    def __repr__(self) -> str:
        return f'<Blank {self.name}>'


class ExaminationBlank(PricingSnapshotMixin, db.Model):
    __tablename__ = 'examination_blanks'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    blank_id = db.Column(db.Integer, db.ForeignKey('blanks.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_blanks')
    blank = db.relationship('Blank')

    @property
    def _source(self):
        return self.blank


class ExaminationDirection(PricingSnapshotMixin, db.Model):
    __tablename__ = 'examination_directions'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey('doctor_directions.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)
    is_visited = db.Column(db.Boolean, default=False, nullable=False)
    visited_at = db.Column(db.DateTime, nullable=True)

    examination = db.relationship('Examination', back_populates='exam_directions')
    direction = db.relationship('DoctorDirection')
    doctor = db.relationship('User', foreign_keys=[doctor_id])

    @property
    def _source(self):
        return self.direction


class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    rooms = db.relationship('Room', back_populates='department', lazy='dynamic')

    def __repr__(self) -> str:
        return f'<Department {self.name}>'


class RoomType(db.Model):
    __tablename__ = 'room_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    rooms = db.relationship('Room', back_populates='room_type', lazy='dynamic')

    def __repr__(self) -> str:
        return f'<RoomType {self.name}>'


class Room(db.Model):
    __tablename__ = 'rooms'
    __table_args__ = (
        db.UniqueConstraint('department_id', 'name', name='uq_room_department_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    room_type_id = db.Column(db.Integer, db.ForeignKey('room_types.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    room_type = db.relationship('RoomType', back_populates='rooms')
    department = db.relationship('Department', back_populates='rooms')
    beds = db.relationship('Bed', back_populates='room', lazy='dynamic')

    def __repr__(self) -> str:
        return f'<Room {self.name}>'


class Bed(db.Model):
    __tablename__ = 'beds'
    __table_args__ = (
        db.UniqueConstraint('room_id', 'name', name='uq_bed_room_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    room = db.relationship('Room', back_populates='beds')

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<Bed {self.name}>'


meal_departments = db.Table(
    'meal_departments',
    db.Column('meal_id', db.Integer, db.ForeignKey('meals.id'), primary_key=True),
    db.Column('department_id', db.Integer, db.ForeignKey('departments.id'), primary_key=True),
)


class Meal(db.Model):
    __tablename__ = 'meals'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    note = db.Column(db.String(500), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    departments = db.relationship(
        'Department', secondary=meal_departments, lazy='subquery',
        backref=db.backref('meals', lazy='dynamic'),
    )

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<Meal {self.name}>'


class EarningPlan(db.Model):
    """Monthly earning target for a doctor / analysis-responsible, set by the
    senior cashier. Earnings are measured against doctor-direction income."""
    __tablename__ = 'earning_plans'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'year', 'month', name='uq_earning_plan_user_month'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f'<EarningPlan user={self.user_id} {self.year}-{self.month:02d} amount={self.amount}>'


class Hospitalization(db.Model):
    """A patient's stay in an inpatient department.

    Opened by the department head (who also supplies the history number and the
    relatives' phones), then a senior nurse of the same department assigns the
    room and bed. Department and history number are kept on the record itself,
    so past stays stay correct even if the staff's departments change later.
    """
    __tablename__ = 'hospitalizations'

    STATUS_ACTIVE = 'active'
    STATUS_DISCHARGED = 'discharged'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)
    history_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_ACTIVE, index=True)

    admitted_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    admitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    discharged_at = db.Column(db.DateTime, nullable=True)
    discharged_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=True)
    bed_assigned_at = db.Column(db.DateTime, nullable=True)
    bed_assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # current attending doctor; every change is also kept in doctor_assignments
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    doctor_assigned_at = db.Column(db.DateTime, nullable=True)
    doctor_assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    patient = db.relationship('Patient', backref=db.backref('hospitalizations', lazy='dynamic'))
    department = db.relationship('Department')
    room = db.relationship('Room')
    bed = db.relationship('Bed')
    admitted_by = db.relationship('User', foreign_keys=[admitted_by_id])
    discharged_by = db.relationship('User', foreign_keys=[discharged_by_id])
    bed_assigned_by = db.relationship('User', foreign_keys=[bed_assigned_by_id])
    doctor = db.relationship('User', foreign_keys=[doctor_id])
    doctor_assigned_by = db.relationship('User', foreign_keys=[doctor_assigned_by_id])
    relatives = db.relationship('HospitalizationRelative', back_populates='hospitalization',
                                cascade='all, delete-orphan')
    bed_stays = db.relationship('HospitalizationBedStay', back_populates='hospitalization',
                                cascade='all, delete-orphan',
                                order_by='HospitalizationBedStay.started_at')
    doctor_assignments = db.relationship('HospitalizationDoctorAssignment',
                                         back_populates='hospitalization',
                                         cascade='all, delete-orphan',
                                         order_by='HospitalizationDoctorAssignment.started_at')
    diary_entries = db.relationship('HospitalizationDiaryEntry', back_populates='hospitalization',
                                    cascade='all, delete-orphan',
                                    order_by='HospitalizationDiaryEntry.created_at.desc()')
    meal_assignments = db.relationship('HospitalizationMealAssignment',
                                       back_populates='hospitalization',
                                       cascade='all, delete-orphan',
                                       order_by='HospitalizationMealAssignment.started_at')

    @property
    def is_open(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    @property
    def has_bed(self) -> bool:
        return self.bed_id is not None

    @property
    def current_bed_stay(self):
        """The period the patient is lying in right now, if any."""
        return next((s for s in self.bed_stays if s.ended_at is None), None)

    @property
    def has_doctor(self) -> bool:
        return self.doctor_id is not None

    @property
    def active_meal_assignments(self):
        """Meals the patient is on right now — several may run at once."""
        return [m for m in self.meal_assignments if m.ended_at is None]

    @property
    def current_doctor_assignment(self):
        return next((a for a in self.doctor_assignments if a.ended_at is None), None)

    @property
    def place_display(self) -> str:
        if not self.has_bed:
            return '—'
        return f'{self.room.name} / {self.bed.name}'

    def __repr__(self) -> str:
        return f'<Hospitalization {self.history_number} patient={self.patient_id}>'


class HospitalizationRelative(db.Model):
    """Contact of a hospitalized patient — who to call."""
    __tablename__ = 'hospitalization_relatives'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'), nullable=False, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    relation = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='relatives')

    def __repr__(self) -> str:
        return f'<HospitalizationRelative {self.full_name} {self.phone_number}>'


class HospitalizationBedStay(db.Model):
    """One period a patient spent in one bed.

    A new row is opened every time the bed changes and closed on the next move
    or on discharge, so a stay that moved between beds keeps every period. The
    bed price and its insurance flag are snapshotted here — changing the price
    in the catalogue later must not rewrite what a past period cost.
    """
    __tablename__ = 'hospitalization_bed_stays'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=False)

    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    ended_at = db.Column(db.DateTime, nullable=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='bed_stays')
    room = db.relationship('Room')
    bed = db.relationship('Bed')
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    @property
    def place_display(self) -> str:
        return f'{self.room.name} / {self.bed.name}'

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<HospitalizationBedStay h={self.hospitalization_id} bed={self.bed_id}>'


class HospitalizationDoctorAssignment(db.Model):
    """One period a patient was in the care of one doctor.

    The department head assigns the attending doctor; assigning another one
    closes the running period and opens a new one, so it stays visible who was
    responsible on any given day.
    """
    __tablename__ = 'hospitalization_doctor_assignments'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    ended_at = db.Column(db.DateTime, nullable=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='doctor_assignments')
    doctor = db.relationship('User', foreign_keys=[doctor_id])
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    def __repr__(self) -> str:
        return f'<HospitalizationDoctorAssignment h={self.hospitalization_id} doctor={self.doctor_id}>'


class HospitalizationDiaryEntry(db.Model):
    """A doctor's progress note (gündelik) on a hospitalized patient.

    Entries are never deleted. The author may correct their own note within
    EDIT_WINDOW of writing it — after that the record is fixed, and any
    correction made inside the window is marked as edited.
    """
    __tablename__ = 'hospitalization_diary_entries'

    EDIT_WINDOW = timedelta(hours=24)

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    complaints = db.Column(db.Text, nullable=True)
    objective = db.Column(db.Text, nullable=True)
    dynamics = db.Column(db.Text, nullable=True)
    plan = db.Column(db.Text, nullable=True)

    temperature = db.Column(db.Numeric(4, 1), nullable=True)
    blood_pressure = db.Column(db.String(20), nullable=True)
    pulse = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True)

    hospitalization = db.relationship('Hospitalization', back_populates='diary_entries')
    author = db.relationship('User', foreign_keys=[author_id])

    @property
    def is_edited(self) -> bool:
        return self.updated_at is not None

    @property
    def edit_deadline(self):
        return self.created_at + self.EDIT_WINDOW

    def is_editable_by(self, user) -> bool:
        return user.id == self.author_id and datetime.now() <= self.edit_deadline

    @property
    def has_vitals(self) -> bool:
        return any(v is not None for v in (self.temperature, self.blood_pressure, self.pulse))

    @property
    def temperature_display(self) -> str:
        return f'{self.temperature:.1f}' if self.temperature is not None else '—'

    def __repr__(self) -> str:
        return f'<HospitalizationDiaryEntry h={self.hospitalization_id} by={self.author_id}>'


class HospitalizationMealAssignment(db.Model):
    """One period a patient was on one meal, assigned by the senior nurse.

    Unlike a bed, several meals may run at the same time, so each meal has its
    own period. Price and insurance flag are snapshotted at assignment — the
    catalogue may change later without rewriting what a past period cost.
    """
    __tablename__ = 'hospitalization_meal_assignments'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    meal_id = db.Column(db.Integer, db.ForeignKey('meals.id'), nullable=False, index=True)

    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    ended_at = db.Column(db.DateTime, nullable=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ended_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='meal_assignments')
    meal = db.relationship('Meal')
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])
    ended_by = db.relationship('User', foreign_keys=[ended_by_id])

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<HospitalizationMealAssignment h={self.hospitalization_id} meal={self.meal_id}>'
