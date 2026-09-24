from datetime import datetime, timedelta
from decimal import Decimal
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

    # ── Refund ────────────────────────────────────────────────────────────────
    # A paid line may be given back as a whole. `refund_amount` / `refund_discount`
    # freeze what was returned and the insurance discount it carried, because a
    # line without a price of its own still reads it off the catalogue, which
    # may change afterwards.

    @property
    def is_refunded(self):
        return self.refund_id is not None

    @property
    def refund_amount_display(self):
        return f'{self.refund_amount or 0:,.2f}'


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
    analyses = db.relationship('Analysis', back_populates='category', lazy='dynamic')
    blanks = db.relationship('Blank', back_populates='category', lazy='dynamic')
    tools = db.relationship('AnalysisTool', back_populates='direction_category', lazy='dynamic')

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
    # The same categories doctor-directions are grouped in, so a category's
    # income covers both its receptions and its analyses.
    category_id = db.Column(db.Integer, db.ForeignKey('doctor_direction_categories.id'),
                            nullable=True, index=True)

    responsible = db.relationship('User', backref=db.backref('analyses', lazy='dynamic'))
    category = db.relationship('DoctorDirectionCategory', back_populates='analyses')

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

    # Whether anyone has actually asked about allergies. «Nothing on record» and
    # «asked, nothing found» look the same in a list of zero rows, and only one
    # of them is safe to prescribe against — hence the explicit review stamp.
    ALLERGY_UNKNOWN = 'unknown'
    ALLERGY_NONE = 'none'
    ALLERGY_PRESENT = 'present'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    birth_year = db.Column(db.Integer, nullable=False)
    citizenship = db.Column(db.String(100), nullable=False)
    home_address = db.Column(db.String(255), nullable=False)
    passport_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    insurance_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    allergies_reviewed_at = db.Column(db.DateTime, nullable=True)
    allergies_reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    allergies = db.relationship('PatientAllergy', back_populates='patient',
                                cascade='all, delete-orphan',
                                order_by='PatientAllergy.created_at.desc()')
    allergies_reviewed_by = db.relationship('User', foreign_keys=[allergies_reviewed_by_id])

    @property
    def age(self) -> int:
        return datetime.now().year - self.birth_year

    @property
    def active_allergies(self):
        """Allergies still in force — a withdrawn one is kept but not warned about."""
        return [a for a in self.allergies if a.is_active]

    @property
    def allergy_status(self) -> str:
        if self.active_allergies:
            return self.ALLERGY_PRESENT
        return self.ALLERGY_NONE if self.allergies_reviewed_at else self.ALLERGY_UNKNOWN

    @property
    def has_dangerous_allergy(self) -> bool:
        return any(a.is_dangerous for a in self.active_allergies)

    def __repr__(self) -> str:
        return f'<Patient {self.full_name}>'


class PatientAllergy(db.Model):
    """A substance this patient reacts to. Kept on the patient, not on a stay —
    an allergy does not end at discharge.

    Rows are never deleted: one entered by mistake is withdrawn with a reason,
    so it stays visible that it was once believed and by whom.
    """
    __tablename__ = 'patient_allergies'

    SEVERITY_MILD = 'mild'
    SEVERITY_MODERATE = 'moderate'
    SEVERITY_SEVERE = 'severe'
    SEVERITY_ANAPHYLAXIS = 'anaphylaxis'

    SEVERITIES = {
        SEVERITY_MILD: 'Ýeňil',
        SEVERITY_MODERATE: 'Orta',
        SEVERITY_SEVERE: 'Agyr',
        SEVERITY_ANAPHYLAXIS: 'Anafilaksiýa',
    }
    DANGEROUS = (SEVERITY_SEVERE, SEVERITY_ANAPHYLAXIS)

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)

    substance = db.Column(db.String(200), nullable=False)
    reaction = db.Column(db.String(500), nullable=True)
    severity = db.Column(db.String(20), nullable=False, default=SEVERITY_MODERATE)
    note = db.Column(db.String(500), nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    removed_at = db.Column(db.DateTime, nullable=True)
    removed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    remove_reason = db.Column(db.String(500), nullable=True)

    patient = db.relationship('Patient', back_populates='allergies')
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_id])
    removed_by = db.relationship('User', foreign_keys=[removed_by_id])

    @property
    def severity_display(self) -> str:
        return self.SEVERITIES.get(self.severity, self.severity)

    @property
    def is_dangerous(self) -> bool:
        return self.severity in self.DANGEROUS

    def __repr__(self) -> str:
        return f'<PatientAllergy {self.substance} patient={self.patient_id}>'


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
        'registratura': 'Registratura',
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
    refunds = db.relationship('ExaminationRefund', back_populates='examination',
                              order_by='ExaminationRefund.refunded_at')

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

    @property
    def all_lines(self):
        return (list(self.exam_analyses) + list(self.exam_tools)
                + list(self.exam_blanks) + list(self.exam_directions))

    @property
    def active_lines(self):
        """Lines still standing — refunded ones excluded."""
        return [line for line in self.all_lines if not line.is_refunded]

    @property
    def charged_total(self):
        """What the examination was paid (or is to be paid) in full."""
        return sum((line.effective_total for line in self.all_lines), Decimal('0'))

    @property
    def refunded_total(self):
        return sum((line.refund_amount or Decimal('0')
                    for line in self.all_lines if line.is_refunded), Decimal('0'))

    @property
    def active_total(self):
        return sum((line.effective_total for line in self.active_lines), Decimal('0'))

    @property
    def has_refunds(self):
        return any(line.is_refunded for line in self.all_lines)

    @property
    def is_fully_refunded(self):
        lines = self.all_lines
        return bool(lines) and all(line.is_refunded for line in lines)

    def __repr__(self) -> str:
        return f'<Examination {self.id}>'


class ExaminationRefund(db.Model):
    """Money given back for some paid lines of an examination.

    One refund may cover several lines at once, under one reason. Each line
    points at its refund and keeps the amount returned for it, so the refund's
    total is the sum over its lines. Reports book a refund on the day it was
    made, against the cashier who made it — the day of payment is left as it was.
    """
    __tablename__ = 'examination_refunds'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    refunded_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    refunded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(500), nullable=False)

    examination = db.relationship('Examination', back_populates='refunds')
    refunded_by = db.relationship('User', foreign_keys=[refunded_by_id])
    analyses = db.relationship('ExaminationAnalysis', back_populates='refund')
    tools = db.relationship('ExaminationAnalysisTool', back_populates='refund')
    blanks = db.relationship('ExaminationBlank', back_populates='refund')
    directions = db.relationship('ExaminationDirection', back_populates='refund')

    @property
    def lines(self):
        return list(self.analyses) + list(self.tools) + list(self.blanks) + list(self.directions)

    @property
    def total(self):
        return sum((line.refund_amount or Decimal('0') for line in self.lines), Decimal('0'))

    @property
    def total_display(self):
        return f'{self.total:,.2f}'

    def __repr__(self) -> str:
        return f'<ExaminationRefund {self.id}>'


class ExaminationAnalysis(PricingSnapshotMixin, db.Model):
    __tablename__ = 'examination_analyses'

    id = db.Column(db.Integer, primary_key=True)
    examination_id = db.Column(db.Integer, db.ForeignKey('examinations.id'), nullable=False)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analyses.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    is_insurance = db.Column(db.Boolean, nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)
    refund_id = db.Column(db.Integer, db.ForeignKey('examination_refunds.id'),
                          nullable=True, index=True)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=True)
    refund_discount = db.Column(db.Numeric(10, 2), nullable=True)
    is_submitted = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_analyses')
    refund = db.relationship('ExaminationRefund', back_populates='analyses')
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
    refund_id = db.Column(db.Integer, db.ForeignKey('examination_refunds.id'),
                          nullable=True, index=True)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=True)
    refund_discount = db.Column(db.Numeric(10, 2), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_tools')
    refund = db.relationship('ExaminationRefund', back_populates='tools')
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
    # A second, independent grouping: the doctor-direction category the tool's
    # income counts towards. `category_id` / `subcategory_id` above are the
    # tools' own tree, used by the tools report.
    direction_category_id = db.Column(db.Integer, db.ForeignKey('doctor_direction_categories.id'),
                                      nullable=True, index=True)

    analyses = db.relationship(
        'Analysis', secondary=analysis_tool_analyses, lazy='subquery',
        backref=db.backref('tools', lazy='dynamic'),
    )
    category = db.relationship('AnalysisToolCategory')
    subcategory = db.relationship('AnalysisToolSubcategory')
    direction_category = db.relationship('DoctorDirectionCategory', back_populates='tools')

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
    # The doctor-direction category the blank's income counts towards.
    category_id = db.Column(db.Integer, db.ForeignKey('doctor_direction_categories.id'),
                            nullable=True, index=True)

    analyses = db.relationship(
        'Analysis', secondary=blank_analyses, lazy='subquery',
        backref=db.backref('blanks', lazy='dynamic'),
    )
    category = db.relationship('DoctorDirectionCategory', back_populates='blanks')

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
    refund_id = db.Column(db.Integer, db.ForeignKey('examination_refunds.id'),
                          nullable=True, index=True)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=True)
    refund_discount = db.Column(db.Numeric(10, 2), nullable=True)

    examination = db.relationship('Examination', back_populates='exam_blanks')
    refund = db.relationship('ExaminationRefund', back_populates='blanks')
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
    refund_id = db.Column(db.Integer, db.ForeignKey('examination_refunds.id'),
                          nullable=True, index=True)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=True)
    refund_discount = db.Column(db.Numeric(10, 2), nullable=True)
    is_visited = db.Column(db.Boolean, default=False, nullable=False)
    visited_at = db.Column(db.DateTime, nullable=True)

    examination = db.relationship('Examination', back_populates='exam_directions')
    refund = db.relationship('ExaminationRefund', back_populates='directions')
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


class InpatientBillingMixin:
    """Shared money logic for one charge line of an inpatient stay.

    The outpatient section prices an `Examination` line the same way
    (`PricingSnapshotMixin`), but there the price may still fall back to the
    catalogue; here every line already carries its own snapshot, taken when the
    bed, meal, drug, order or operation was written down. What is left is the
    insurance discount, and that depends on the *stay* — whether the patient
    lying in had insurance when they were admitted.

    Subclasses must expose: self.price, self.is_insurance, self.hospitalization,
    and — unless one unit is billed — self.billed_quantity.
    """

    PAYMENT_CASH = 'cash'
    PAYMENT_TERMINAL = 'terminal'
    PAYMENT_METHODS = (PAYMENT_CASH, PAYMENT_TERMINAL)

    @property
    def billed_quantity(self):
        """How many units this line is billed for. Beds and meals count days,
        everything else counts pieces."""
        return getattr(self, 'quantity', 1) or 1

    @property
    def has_discount(self) -> bool:
        return bool(self.hospitalization.patient_has_insurance and self.is_insurance)

    @property
    def effective_price(self):
        return self.price / 2 if self.has_discount else self.price

    @property
    def full_total(self):
        return self.price * self.billed_quantity

    @property
    def effective_total(self):
        return self.effective_price * self.billed_quantity

    @property
    def full_total_display(self) -> str:
        return f'{self.full_total:,.2f}'

    @property
    def effective_total_display(self) -> str:
        return f'{self.effective_total:,.2f}'

    @property
    def bill_note(self) -> str:
        """Second line of a bill row — what makes this charge identifiable."""
        return ''

    @property
    def bill_ref(self) -> str:
        """Key identifying this line in the payment form.

        Not the id: the «order» group of a bill merges three tables whose ids
        run independently, so an analysis order, a tool order and a blank order
        routinely share one. Keyed by id alone they would collapse into a single
        radio group and be stamped with one payment method — the total would
        still be right, but the cash/terminal split a cashier's day is counted
        in would not. The table name pins a line to the table it came from.
        """
        return f'{self.__tablename__}_{self.id}'


def billed_period_display(started_at, ended_at) -> str:
    start = started_at.strftime('%d.%m.%Y')
    return f"{start} → {ended_at.strftime('%d.%m.%Y') if ended_at else 'häzir'}"


def billed_days(started_at, ended_at) -> int:
    """Nights a period is charged for. The day it started always counts, so a
    stay that began and ended the same day is one day, exactly as
    `Hospitalization.bed_days` counts the stay as a whole."""
    end = ended_at or datetime.now()
    return max(1, (end.date() - started_at.date()).days)


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

    # How the stay ended. Recorded together with the closing epicrisis — a
    # discharge without an outcome says nothing about what happened.
    OUTCOME_RECOVERED = 'recovered'
    OUTCOME_IMPROVED = 'improved'
    OUTCOME_UNCHANGED = 'unchanged'
    OUTCOME_WORSENED = 'worsened'
    OUTCOME_TRANSFERRED = 'transferred'
    OUTCOME_DIED = 'died'

    OUTCOMES = {
        OUTCOME_RECOVERED: 'Sagaldy',
        OUTCOME_IMPROVED: 'Ýagdaýy gowulaşdy',
        OUTCOME_UNCHANGED: 'Ýagdaýy üýtgemedi',
        OUTCOME_WORSENED: 'Ýagdaýy erbetleşdi',
        OUTCOME_TRANSFERRED: 'Başga edara geçirildi',
        OUTCOME_DIED: 'Aradan çykdy',
    }

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)
    history_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_ACTIVE, index=True)

    admitted_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    admitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    discharged_at = db.Column(db.DateTime, nullable=True)
    discharged_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # filled in when the stay is closed; nullable because stays opened before
    # the discharge summary existed have none
    outcome = db.Column(db.String(20), nullable=True)
    epicrisis = db.Column(db.Text, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)

    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=True)
    bed_assigned_at = db.Column(db.DateTime, nullable=True)
    bed_assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # current attending doctor; every change is also kept in doctor_assignments
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    doctor_assigned_at = db.Column(db.DateTime, nullable=True)
    doctor_assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Cashier's side of a stay. The whole stay is settled in one payment (the
    # natural moment is discharge), so what is charged is whatever the bill
    # holds at that moment; `paid_total` keeps what was actually taken, so a
    # line written after the payment is visible as an unpaid remainder instead
    # of silently disappearing into a boolean.
    patient_has_insurance = db.Column(db.Boolean, default=False, nullable=True)
    is_paid = db.Column(db.Boolean, default=False, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    paid_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    paid_total = db.Column(db.Numeric(10, 2), nullable=True)

    patient = db.relationship('Patient', backref=db.backref('hospitalizations', lazy='dynamic'))
    department = db.relationship('Department')
    room = db.relationship('Room')
    bed = db.relationship('Bed')
    admitted_by = db.relationship('User', foreign_keys=[admitted_by_id])
    discharged_by = db.relationship('User', foreign_keys=[discharged_by_id])
    bed_assigned_by = db.relationship('User', foreign_keys=[bed_assigned_by_id])
    paid_by = db.relationship('User', foreign_keys=[paid_by_id])
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
    medication_orders = db.relationship('HospitalizationMedicationOrder',
                                        back_populates='hospitalization',
                                        cascade='all, delete-orphan',
                                        order_by='HospitalizationMedicationOrder.started_at.desc()')
    medication_dispenses = db.relationship('HospitalizationMedicationDispense',
                                           back_populates='hospitalization',
                                           cascade='all, delete-orphan',
                                           order_by='HospitalizationMedicationDispense.given_at.desc()')
    diagnoses = db.relationship('HospitalizationDiagnosis', back_populates='hospitalization',
                                cascade='all, delete-orphan',
                                order_by='HospitalizationDiagnosis.created_at.desc()')
    vital_records = db.relationship('HospitalizationVitalRecord', back_populates='hospitalization',
                                    cascade='all, delete-orphan',
                                    order_by='HospitalizationVitalRecord.measured_at.desc()')
    operations = db.relationship('HospitalizationOperation', back_populates='hospitalization',
                                 cascade='all, delete-orphan',
                                 order_by='HospitalizationOperation.created_at.desc()')
    admission_exam = db.relationship('HospitalizationAdmissionExam',
                                     back_populates='hospitalization',
                                     cascade='all, delete-orphan', uselist=False)
    analysis_orders = db.relationship('HospitalizationAnalysisOrder',
                                      back_populates='hospitalization',
                                      cascade='all, delete-orphan',
                                      order_by='HospitalizationAnalysisOrder.ordered_at.desc()')
    tool_orders = db.relationship('HospitalizationToolOrder', back_populates='hospitalization',
                                  cascade='all, delete-orphan',
                                  order_by='HospitalizationToolOrder.ordered_at.desc()')
    blank_orders = db.relationship('HospitalizationBlankOrder', back_populates='hospitalization',
                                   cascade='all, delete-orphan',
                                   order_by='HospitalizationBlankOrder.ordered_at.desc()')
    consultations = db.relationship('HospitalizationConsultation', back_populates='hospitalization',
                                    cascade='all, delete-orphan',
                                    order_by='HospitalizationConsultation.ordered_at.desc()')
    transfers = db.relationship('HospitalizationTransfer', back_populates='hospitalization',
                                cascade='all, delete-orphan',
                                order_by='HospitalizationTransfer.transferred_at')
    payments = db.relationship('HospitalizationPayment', back_populates='hospitalization',
                               cascade='all, delete-orphan',
                               order_by='HospitalizationPayment.paid_at')

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
    def active_medication_orders(self):
        """Drug orders the patient is on right now."""
        return [o for o in self.medication_orders
                if o.status == HospitalizationMedicationOrder.STATUS_ACTIVE]

    @property
    def current_doctor_assignment(self):
        return next((a for a in self.doctor_assignments if a.ended_at is None), None)

    @property
    def place_display(self) -> str:
        if not self.has_bed:
            return '—'
        return f'{self.room.name} / {self.bed.name}'

    def _latest_diagnosis(self, kind):
        """Diagnoses are append-only; a correction is a newer row of the same
        kind, so the newest one of a kind is the one that counts."""
        return next((d for d in self.diagnoses if d.kind == kind), None)

    @property
    def preliminary_diagnosis(self):
        return self._latest_diagnosis(HospitalizationDiagnosis.KIND_PRELIMINARY)

    @property
    def clinical_diagnosis(self):
        return self._latest_diagnosis(HospitalizationDiagnosis.KIND_CLINICAL)

    @property
    def final_diagnosis(self):
        return self._latest_diagnosis(HospitalizationDiagnosis.KIND_FINAL)

    @property
    def current_diagnosis(self):
        """The most authoritative diagnosis on record — final beats clinical
        beats preliminary, regardless of which was written last."""
        return self.final_diagnosis or self.clinical_diagnosis or self.preliminary_diagnosis

    @property
    def outcome_display(self) -> str:
        return self.OUTCOMES.get(self.outcome, '—')

    @property
    def latest_vitals(self):
        return self.vital_records[0] if self.vital_records else None

    @property
    def planned_operations(self):
        return [o for o in self.operations
                if o.status == HospitalizationOperation.STATUS_PLANNED]

    @property
    def performed_operations(self):
        return [o for o in self.operations
                if o.status == HospitalizationOperation.STATUS_DONE]

    @property
    def bed_days(self) -> int:
        """Calendar days spent in — the day of admission counts as one."""
        end = self.discharged_at or datetime.now()
        return max(1, (end.date() - self.admitted_at.date()).days)

    @property
    def examination_orders(self):
        """Every analysis, study and blank ordered during the stay, newest first.
        Three catalogues, one worklist — the ward thinks in «what is still
        outstanding», not in which table a row lives in."""
        rows = list(self.analysis_orders) + list(self.tool_orders) + list(self.blank_orders)
        return sorted(rows, key=lambda o: o.ordered_at, reverse=True)

    @property
    def pending_examination_orders(self):
        """Ordered but not yet carried out — what the ward still owes."""
        return [o for o in self.examination_orders if o.is_ordered]

    @property
    def pending_consultations(self):
        return [c for c in self.consultations if c.is_ordered]

    @property
    def admission_exam_overdue(self) -> bool:
        """Still no admission examination, and the grace period has run out."""
        if self.admission_exam is not None or not self.is_open:
            return False
        return datetime.now() > self.admitted_at + HospitalizationAdmissionExam.DUE_WITHIN

    # ── Bill ──────────────────────────────────────────────────────────────
    #
    # What the cashier charges for. Each group answers the same question — «is
    # this line still standing?» — because a cancelled order, a cancelled
    # operation and a cancelled dispense are all kept on record and must stay
    # out of the money.

    @property
    def billable_bed_stays(self):
        return list(self.bed_stays)

    @property
    def billable_meal_assignments(self):
        return list(self.meal_assignments)

    @property
    def billable_dispenses(self):
        return [d for d in self.medication_dispenses if not d.is_cancelled]

    @property
    def billable_examination_orders(self):
        """Analyses, studies and blanks that were not called off."""
        rows = [o for o in (list(self.analysis_orders) + list(self.tool_orders)
                            + list(self.blank_orders)) if not o.is_cancelled]
        return sorted(rows, key=lambda o: o.ordered_at)

    @property
    def billable_consultations(self):
        return [c for c in self.consultations if not c.is_cancelled]

    @property
    def billable_operations(self):
        return [o for o in self.operations
                if o.status != HospitalizationOperation.STATUS_CANCELLED]

    @property
    def bill_groups(self):
        """The bill as the cashier reads it: (key, title, lines), empty groups
        included so the payment form always has the same shape."""
        return (
            ('bed', 'Krowat', self.billable_bed_stays),
            ('meal', 'Nahar', self.billable_meal_assignments),
            ('medicine', 'Dermanlar', self.billable_dispenses),
            ('order', 'Barlaglar', self.billable_examination_orders),
            ('consultation', 'Konsultasiýalar', self.billable_consultations),
            ('operation', 'Operasiýalar', self.billable_operations),
        )

    @property
    def bill_lines(self):
        return [line for _, _, lines in self.bill_groups for line in lines]

    @property
    def bill_total(self):
        return sum((line.effective_total for line in self.bill_lines), Decimal('0'))

    @property
    def bill_full_total(self):
        """The bill before the insurance discount — what the 50% is taken off."""
        return sum((line.full_total for line in self.bill_lines), Decimal('0'))

    @property
    def bill_discount(self):
        return self.bill_full_total - self.bill_total

    @property
    def bill_total_display(self) -> str:
        return f'{self.bill_total:,.2f}'

    @property
    def bill_discount_display(self) -> str:
        return f'{self.bill_discount:,.2f}'

    @property
    def paid_total_display(self) -> str:
        return f'{self.paid_total or 0:,.2f}'

    @property
    def unpaid_remainder(self):
        """What the bill has grown by since it was settled. A stay is paid for
        once, but beds and meals keep accruing while the patient lies in — the
        difference is money that was never taken."""
        if not self.is_paid:
            return self.bill_total
        return self.bill_total - (self.paid_total or Decimal('0'))

    @property
    def unpaid_remainder_display(self) -> str:
        return f'{self.unpaid_remainder:,.2f}'

    @property
    def has_unpaid_remainder(self) -> bool:
        return self.is_paid and self.unpaid_remainder > 0

    @property
    def is_settled(self) -> bool:
        """Nothing is owed on the stay right now. A stay whose bill is empty is
        settled without a payment ever having been taken — the ward may not be
        held back over a bill of zero."""
        return self.unpaid_remainder <= 0

    @property
    def is_overpaid(self) -> bool:
        """More was taken than the bill now asks for — a line was cancelled
        after the payment. Kept visible instead of shown as a settled stay."""
        return self.unpaid_remainder < 0

    @property
    def overpaid_display(self) -> str:
        return f'{-self.unpaid_remainder:,.2f}'

    @property
    def unsettled_lines(self):
        """Bill lines no payment has covered yet. A line is stamped with the
        method it was paid by, so an unstamped one is money still owed."""
        return [line for line in self.bill_lines if line.payment_method is None]

    @property
    def accrued_since_payment(self):
        """The part of the remainder no new line accounts for — the bed and the
        meals of a patient who went on lying in after the payment was taken."""
        if not self.is_paid:
            return Decimal('0')
        new_lines = sum((line.effective_total for line in self.unsettled_lines), Decimal('0'))
        return self.unpaid_remainder - new_lines

    @property
    def accrued_since_payment_display(self) -> str:
        return f'{self.accrued_since_payment:,.2f}'

    @property
    def logged_payments_total(self):
        return sum((p.amount for p in self.payments), Decimal('0'))

    @property
    def unlogged_paid_total(self):
        """Money taken before payments began to be kept one by one. Such a stay
        carries only its total, so the log prints it as one undetailed row
        instead of pretending the act was never recorded."""
        return (self.paid_total or Decimal('0')) - self.logged_payments_total

    @property
    def unlogged_paid_total_display(self) -> str:
        return f'{self.unlogged_paid_total:,.2f}'

    @property
    def current_transfer(self):
        """The move that put the patient where they are now, if they were moved."""
        return self.transfers[-1] if self.transfers else None

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


class HospitalizationPayment(db.Model):
    """One payment the cashier took for a stay.

    A stay is meant to be settled in one payment, but the bill does not stand
    still: the bed and the meals keep accruing while the patient lies in, and
    orders written afterwards join it. What is left over is taken in a further
    payment, so a stay may have several — `Hospitalization.paid_total` is their
    sum, and each row keeps who took how much, when, and by which method.

    Every payment splits into cash and terminal because one act may be both:
    the cashier chooses the method per bill line, and the two sides are what a
    cashier's day is counted in.
    """
    __tablename__ = 'hospitalization_payments'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)

    cash_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    terminal_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    paid_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    paid_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='payments')
    paid_by = db.relationship('User', foreign_keys=[paid_by_id])

    @property
    def amount(self):
        return (self.cash_amount or Decimal('0')) + (self.terminal_amount or Decimal('0'))

    @property
    def amount_display(self) -> str:
        return f'{self.amount:,.2f}'

    @property
    def cash_amount_display(self) -> str:
        return f"{self.cash_amount or Decimal('0'):,.2f}"

    @property
    def terminal_amount_display(self) -> str:
        return f"{self.terminal_amount or Decimal('0'):,.2f}"

    def __repr__(self) -> str:
        return f'<HospitalizationPayment h={self.hospitalization_id} amount={self.amount}>'


class HospitalizationBedStay(InpatientBillingMixin, db.Model):
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

    payment_method = db.Column(db.String(10), nullable=True)

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

    @property
    def billed_quantity(self) -> int:
        """A bed is charged by the day it was lain in."""
        return billed_days(self.started_at, self.ended_at)

    @property
    def bill_note(self) -> str:
        return billed_period_display(self.started_at, self.ended_at)

    @property
    def bill_name(self) -> str:
        return f'Krowat {self.place_display}'

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


class HospitalizationTransfer(db.Model):
    """A move of a running stay from one department to another.

    A transfer is not a discharge: the history number, the diary, the bill and
    every past record stay with the patient, only the department changes. What
    belonged to the department that was left does not travel — the bed and the
    attending doctor are released by the move, and the receiving department
    gives its own; the meals stop for the same reason, since a meal is served
    by the department that ordered it.

    The reason is required: a patient who appears in another ward with nothing
    said about why is exactly what this record exists to prevent.
    """
    __tablename__ = 'hospitalization_transfers'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    from_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    to_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)

    reason = db.Column(db.String(500), nullable=False)

    transferred_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    transferred_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='transfers')
    from_department = db.relationship('Department', foreign_keys=[from_department_id])
    to_department = db.relationship('Department', foreign_keys=[to_department_id])
    transferred_by = db.relationship('User', foreign_keys=[transferred_by_id])

    @property
    def route_display(self) -> str:
        return f'{self.from_department.name} → {self.to_department.name}'

    def __repr__(self) -> str:
        return (f'<HospitalizationTransfer h={self.hospitalization_id} '
                f'{self.from_department_id}->{self.to_department_id}>')


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


class HospitalizationMealAssignment(InpatientBillingMixin, db.Model):
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

    payment_method = db.Column(db.String(10), nullable=True)

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

    @property
    def billed_quantity(self) -> int:
        """A meal is charged by the day the patient was on it."""
        return billed_days(self.started_at, self.ended_at)

    @property
    def bill_note(self) -> str:
        return billed_period_display(self.started_at, self.ended_at)

    @property
    def bill_name(self) -> str:
        return self.meal.name

    def __repr__(self) -> str:
        return f'<HospitalizationMealAssignment h={self.hospitalization_id} meal={self.meal_id}>'


def format_quantity(value) -> str:
    """Drug amounts are kept with two decimals, but whole ones must read as
    whole: 10 tablets is «10», not «10.00»; half a tablet stays «0.5»."""
    if value is None:
        return '0'
    text = f'{value:,.2f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


class Medicine(db.Model):
    """A drug in the hospital-wide catalogue, kept by the administrator.

    The catalogue is not bound to departments — what a department actually has
    is expressed by its stock rows, so a drug never has to be re-registered to
    move between wards.
    """
    __tablename__ = 'medicines'

    UNITS = {
        'tablet': 'tabletka',
        'ampoule': 'ampula',
        'vial': 'flakon',
        'ml': 'ml',
        'g': 'gram',
        'piece': 'sany',
    }

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    unit = db.Column(db.String(20), nullable=False, default='piece')
    note = db.Column(db.String(500), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @property
    def unit_display(self) -> str:
        return self.UNITS.get(self.unit, self.unit)

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<Medicine {self.name}>'


class DepartmentMedicineStock(db.Model):
    """How much of one drug a department has right now.

    The running balance lives here so the warehouse page is one query, while
    every change that produced it is kept in MedicineStockMovement. The two are
    always written together, in one transaction.
    """
    __tablename__ = 'department_medicine_stocks'
    __table_args__ = (
        db.UniqueConstraint('department_id', 'medicine_id', name='uq_department_medicine'),
    )

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False, index=True)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    department = db.relationship('Department')
    medicine = db.relationship('Medicine')

    @property
    def quantity_display(self) -> str:
        return format_quantity(self.quantity)

    def __repr__(self) -> str:
        return f'<DepartmentMedicineStock dep={self.department_id} med={self.medicine_id}>'


class MedicineStockMovement(db.Model):
    """One change of a department's stock — the only way a balance may move.

    Quantity is signed: a receipt is positive, a dispense or a write-off is
    negative. balance_after is the remainder right after this row was written,
    so the journal reads like a bank statement and any drift is visible.
    """
    __tablename__ = 'medicine_stock_movements'

    KIND_IN = 'in'
    KIND_OUT = 'out'
    KIND_WRITEOFF = 'writeoff'
    KIND_CORRECTION = 'correction'

    KINDS = {
        KIND_IN: 'Girdeji',
        KIND_OUT: 'Syrkawa berildi',
        KIND_WRITEOFF: 'Hasapdan öçürildi',
        KIND_CORRECTION: 'Düzediş',
    }

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    balance_after = db.Column(db.Numeric(10, 2), nullable=False)
    note = db.Column(db.String(500), nullable=True)
    dispense_id = db.Column(db.Integer, db.ForeignKey('hospitalization_medication_dispenses.id'),
                            nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    department = db.relationship('Department')
    medicine = db.relationship('Medicine')
    dispense = db.relationship('HospitalizationMedicationDispense', foreign_keys=[dispense_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def kind_display(self) -> str:
        return self.KINDS.get(self.kind, self.kind)

    @property
    def is_incoming(self) -> bool:
        return self.quantity > 0

    @property
    def quantity_display(self) -> str:
        sign = '+' if self.is_incoming else '−'
        return f'{sign}{format_quantity(abs(self.quantity))}'

    @property
    def balance_after_display(self) -> str:
        return format_quantity(self.balance_after)

    def __repr__(self) -> str:
        return f'<MedicineStockMovement {self.kind} {self.quantity} med={self.medicine_id}>'


class HospitalizationMedicationOrder(db.Model):
    """A doctor's drug order (bellenme) for a hospitalized patient.

    dose and quantity_per_dose are deliberately separate: «500 mg» is the
    clinical instruction, «2 tabletka» is what the nurse takes off the shelf.
    Merging them would either break the stock count or make the doctor think in
    packages. Nothing here is deleted — an order that is called off is stopped.
    """
    __tablename__ = 'hospitalization_medication_orders'

    STATUS_ACTIVE = 'active'
    STATUS_STOPPED = 'stopped'
    STATUS_FINISHED = 'finished'

    STATUSES = {
        STATUS_ACTIVE: 'Işjeň',
        STATUS_STOPPED: 'Bes edilen',
        STATUS_FINISHED: 'Tamamlanan',
    }

    ROUTES = {
        'oral': 'Içmek',
        'im': 'Myşsa içine (m/i)',
        'iv': 'Wena içine (w/i)',
        'sc': 'Deri astyna (d/a)',
        'external': 'Daşyndan',
        'other': 'Başga',
    }

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    dose = db.Column(db.String(100), nullable=False)
    route = db.Column(db.String(20), nullable=False, default='oral')
    frequency = db.Column(db.String(100), nullable=True)
    quantity_per_dose = db.Column(db.Numeric(10, 2), nullable=False, default=1)

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    planned_end_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default=STATUS_ACTIVE, index=True)
    stopped_at = db.Column(db.DateTime, nullable=True)
    stopped_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='medication_orders')
    medicine = db.relationship('Medicine')
    doctor = db.relationship('User', foreign_keys=[doctor_id])
    stopped_by = db.relationship('User', foreign_keys=[stopped_by_id])
    dispenses = db.relationship('HospitalizationMedicationDispense', back_populates='order',
                                cascade='all, delete-orphan',
                                order_by='HospitalizationMedicationDispense.given_at.desc()')

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    @property
    def status_display(self) -> str:
        return self.STATUSES.get(self.status, self.status)

    @property
    def route_display(self) -> str:
        return self.ROUTES.get(self.route, self.route)

    @property
    def quantity_per_dose_display(self) -> str:
        return format_quantity(self.quantity_per_dose)

    @property
    def live_dispenses(self):
        """Dispenses that still count — a cancelled one is kept but not counted."""
        return [d for d in self.dispenses if not d.is_cancelled]

    @property
    def dispensed_total(self):
        return sum((d.quantity for d in self.live_dispenses), start=0)

    @property
    def dispensed_total_display(self) -> str:
        return format_quantity(self.dispensed_total)

    def __repr__(self) -> str:
        return f'<HospitalizationMedicationOrder h={self.hospitalization_id} med={self.medicine_id}>'


class HospitalizationMedicationDispense(InpatientBillingMixin, db.Model):
    """One act of handing a drug to a patient, written by the senior nurse.

    Price and insurance flag are snapshotted here, exactly as bed stays and
    meals do it — what a past dispense cost must not change when the catalogue
    price does. A dispense is never deleted: a mistake made within
    CANCEL_WINDOW is cancelled, which returns the amount to the stock through a
    compensating movement.
    """
    __tablename__ = 'hospitalization_medication_dispenses'

    CANCEL_WINDOW = timedelta(hours=24)

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('hospitalization_medication_orders.id'),
                         nullable=False, index=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicines.id'), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)

    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    payment_method = db.Column(db.String(10), nullable=True)

    given_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    given_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    note = db.Column(db.String(500), nullable=True)

    is_cancelled = db.Column(db.Boolean, nullable=False, default=False)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    order = db.relationship('HospitalizationMedicationOrder', back_populates='dispenses')
    hospitalization = db.relationship('Hospitalization', back_populates='medication_dispenses')
    medicine = db.relationship('Medicine')
    department = db.relationship('Department')
    given_by = db.relationship('User', foreign_keys=[given_by_id])
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_id])

    @property
    def quantity_display(self) -> str:
        return format_quantity(self.quantity)

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    @property
    def total(self):
        return self.price * self.quantity

    @property
    def total_display(self) -> str:
        return f'{self.total:,.2f}'

    @property
    def bill_name(self) -> str:
        return f'{self.medicine.name} — {self.quantity_display} {self.medicine.unit_display}'

    @property
    def bill_note(self) -> str:
        return f"berlen {self.given_at.strftime('%d.%m.%Y %H:%M')}"

    @property
    def cancel_deadline(self):
        return self.given_at + self.CANCEL_WINDOW

    def is_cancellable_by(self, user) -> bool:
        return (not self.is_cancelled
                and user.id == self.given_by_id
                and datetime.now() <= self.cancel_deadline)

    def __repr__(self) -> str:
        return f'<HospitalizationMedicationDispense order={self.order_id} qty={self.quantity}>'


class HospitalizationDiagnosis(db.Model):
    """A diagnosis written on a stay — preliminary on admission, clinical once
    the picture is clear, final at discharge.

    Rows are append-only: correcting a diagnosis adds a newer row of the same
    kind rather than overwriting the old one, so it stays visible what was
    thought when. The newest row of a kind is the one in force.
    """
    __tablename__ = 'hospitalization_diagnoses'

    KIND_PRELIMINARY = 'preliminary'
    KIND_CLINICAL = 'clinical'
    KIND_FINAL = 'final'

    KINDS = {
        KIND_PRELIMINARY: 'Çaklama diagnoz',
        KIND_CLINICAL: 'Kliniki diagnoz',
        KIND_FINAL: 'Jemleýji diagnoz',
    }

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    text = db.Column(db.String(500), nullable=False)
    # ICD-10 is kept as a free code: there is no classifier table in the system
    # yet, and forcing one would block writing a diagnosis at all
    code = db.Column(db.String(20), nullable=True)
    note = db.Column(db.String(500), nullable=True)

    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='diagnoses')
    author = db.relationship('User', foreign_keys=[author_id])

    @property
    def kind_display(self) -> str:
        return self.KINDS.get(self.kind, self.kind)

    @property
    def full_text(self) -> str:
        return f'{self.text} ({self.code})' if self.code else self.text

    def __repr__(self) -> str:
        return f'<HospitalizationDiagnosis {self.kind} h={self.hospitalization_id}>'


class HospitalizationVitalRecord(db.Model):
    """One round of measurements on a patient — the ward nurse's temperature
    sheet (temperatura sanawy).

    This is the nurse's own record and is deliberately separate from the
    doctor's diary: the nurse measures several times a day, the doctor writes a
    note once. Entries are never deleted; the author may fix an obvious slip
    within EDIT_WINDOW of writing it.
    """
    __tablename__ = 'hospitalization_vital_records'

    EDIT_WINDOW = timedelta(hours=12)

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)

    measured_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    temperature = db.Column(db.Numeric(4, 1), nullable=True)
    pulse = db.Column(db.Integer, nullable=True)
    # kept as two numbers rather than the diary's «120/80» string — a sheet has
    # to be filtered, charted and checked for range
    systolic = db.Column(db.Integer, nullable=True)
    diastolic = db.Column(db.Integer, nullable=True)
    respiratory_rate = db.Column(db.Integer, nullable=True)
    note = db.Column(db.String(500), nullable=True)

    recorded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True)

    hospitalization = db.relationship('Hospitalization', back_populates='vital_records')
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_id])

    @property
    def is_edited(self) -> bool:
        return self.updated_at is not None

    @property
    def edit_deadline(self):
        return self.created_at + self.EDIT_WINDOW

    def is_editable_by(self, user) -> bool:
        return user.id == self.recorded_by_id and datetime.now() <= self.edit_deadline

    @property
    def temperature_display(self) -> str:
        return f'{self.temperature:.1f}' if self.temperature is not None else '—'

    @property
    def pressure_display(self) -> str:
        if self.systolic is None or self.diastolic is None:
            return '—'
        return f'{self.systolic}/{self.diastolic}'

    @property
    def has_fever(self) -> bool:
        return self.temperature is not None and self.temperature >= 37.5

    def __repr__(self) -> str:
        return f'<HospitalizationVitalRecord h={self.hospitalization_id} at={self.measured_at}>'


class Operation(db.Model):
    """A surgery or procedure in the hospital-wide catalogue, kept by the
    administrator. Like the drug catalogue it is not bound to departments."""
    __tablename__ = 'operations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    note = db.Column(db.String(500), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    def __repr__(self) -> str:
        return f'<Operation {self.name}>'


operation_assistants = db.Table(
    'hospitalization_operation_assistants',
    db.Column('operation_id', db.Integer, db.ForeignKey('hospitalization_operations.id'),
              primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
)


class HospitalizationOperation(InpatientBillingMixin, db.Model):
    """One surgery on a hospitalized patient: planned first, then written up.

    Price and insurance flag are snapshotted when the record is created, as
    everywhere else in the stay. A cancelled operation keeps its row — it is
    excluded from the bill by status, never by deletion.
    """
    __tablename__ = 'hospitalization_operations'

    STATUS_PLANNED = 'planned'
    STATUS_DONE = 'done'
    STATUS_CANCELLED = 'cancelled'

    STATUSES = {
        STATUS_PLANNED: 'Meýilleşdirilen',
        STATUS_DONE: 'Geçirilen',
        STATUS_CANCELLED: 'Ýatyrylan',
    }

    ANESTHESIA = {
        'none': 'Ýok',
        'local': 'Ýerli agyrsyzlandyrma',
        'regional': 'Regionar agyrsyzlandyrma',
        'spinal': 'Spinal agyrsyzlandyrma',
        'general': 'Umumy narkoz',
    }

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    operation_id = db.Column(db.Integer, db.ForeignKey('operations.id'), nullable=False, index=True)

    surgeon_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    anesthesiologist_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    anesthesia = db.Column(db.String(20), nullable=False, default='none')

    planned_at = db.Column(db.DateTime, nullable=True)
    performed_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default=STATUS_PLANNED, index=True)

    indication = db.Column(db.String(500), nullable=True)
    protocol = db.Column(db.Text, nullable=True)
    complications = db.Column(db.String(500), nullable=True)

    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)
    payment_method = db.Column(db.String(10), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    performed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancel_reason = db.Column(db.String(500), nullable=True)

    hospitalization = db.relationship('Hospitalization', back_populates='operations')
    operation = db.relationship('Operation')
    surgeon = db.relationship('User', foreign_keys=[surgeon_id])
    anesthesiologist = db.relationship('User', foreign_keys=[anesthesiologist_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    performed_by = db.relationship('User', foreign_keys=[performed_by_id])
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_id])
    assistants = db.relationship('User', secondary=operation_assistants, lazy='subquery')

    @property
    def is_planned(self) -> bool:
        return self.status == self.STATUS_PLANNED

    @property
    def is_done(self) -> bool:
        return self.status == self.STATUS_DONE

    @property
    def status_display(self) -> str:
        return self.STATUSES.get(self.status, self.status)

    @property
    def anesthesia_display(self) -> str:
        return self.ANESTHESIA.get(self.anesthesia, self.anesthesia)

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    @property
    def billed_quantity(self) -> int:
        """One surgery is one charge — the mixin's totals expect a count."""
        return 1

    @property
    def bill_name(self) -> str:
        return self.operation.name

    @property
    def bill_note(self) -> str:
        when = self.happened_at.strftime('%d.%m.%Y') if self.happened_at else '—'
        return f'{when} — {self.status_display.lower()}'

    @property
    def happened_at(self):
        """When it took place, or is meant to."""
        return self.performed_at or self.planned_at

    def __repr__(self) -> str:
        return f'<HospitalizationOperation {self.status} h={self.hospitalization_id}>'


class HospitalizationAdmissionExam(db.Model):
    """The doctor's examination on admission (ilkinji gözden geçirme).

    One per stay — this is the opening document of the case history, not a
    progress note, so it is deliberately a different shape from the diary:
    history of the illness and of the life, status by systems, the reasoning
    behind the diagnosis and the plan. The author may correct it within
    EDIT_WINDOW; after that it is fixed like every other record here.

    Allergies are asked about here but stored on the patient — see
    PatientAllergy — because they outlive the stay.
    """
    __tablename__ = 'hospitalization_admission_exams'
    __table_args__ = (
        db.UniqueConstraint('hospitalization_id', name='uq_admission_exam_hospitalization'),
    )

    EDIT_WINDOW = timedelta(hours=24)
    # how long after admission the exam may be missing before it is chased up
    DUE_WITHIN = timedelta(hours=24)

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    complaints = db.Column(db.Text, nullable=False)
    anamnesis_morbi = db.Column(db.Text, nullable=False)
    anamnesis_vitae = db.Column(db.Text, nullable=True)
    objective_status = db.Column(db.Text, nullable=False)
    local_status = db.Column(db.Text, nullable=True)
    diagnosis_rationale = db.Column(db.Text, nullable=True)
    examination_plan = db.Column(db.Text, nullable=True)
    treatment_plan = db.Column(db.Text, nullable=True)

    temperature = db.Column(db.Numeric(4, 1), nullable=True)
    pulse = db.Column(db.Integer, nullable=True)
    systolic = db.Column(db.Integer, nullable=True)
    diastolic = db.Column(db.Integer, nullable=True)
    # height and weight live here rather than on the nurse's sheet: they are
    # taken once on admission and are what drug doses are calculated from
    height = db.Column(db.Integer, nullable=True)
    weight = db.Column(db.Numeric(5, 1), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True)

    hospitalization = db.relationship('Hospitalization', back_populates='admission_exam')
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
    def pressure_display(self) -> str:
        if self.systolic is None or self.diastolic is None:
            return '—'
        return f'{self.systolic}/{self.diastolic}'

    @property
    def temperature_display(self) -> str:
        return f'{self.temperature:.1f}' if self.temperature is not None else '—'

    @property
    def weight_display(self) -> str:
        return f'{self.weight:g}' if self.weight is not None else '—'

    @property
    def bmi(self):
        """Body mass index, when both height and weight were taken."""
        if not self.height or not self.weight:
            return None
        metres = self.height / 100
        return round(float(self.weight) / (metres * metres), 1)

    def __repr__(self) -> str:
        return f'<HospitalizationAdmissionExam h={self.hospitalization_id}>'


# ── What the ward orders: analyses, studies, blanks, consultations ────────────


class InpatientOrderMixin:
    """Shared lifecycle of anything a ward doctor orders for a lying patient.

    The catalogues are the same ones the outpatient section sells from, but the
    orders themselves are entirely separate records: an inpatient order belongs
    to a stay, never to an `Examination`, and is neither paid for nor closed
    through the cashier. Reusing the catalogue keeps one price list for the
    hospital; keeping the orders apart keeps the two sections from stepping on
    each other.

    A doctor orders it; later the ward writes down what came back, or calls the
    order off with a reason. Nothing is ever deleted — a mistaken order is
    cancelled, so it stays visible that it was once made and by whom. Price and
    insurance flag are snapshotted at ordering, exactly as bed stays, meals and
    dispenses do it: a later change in the catalogue must not rewrite what a
    past order cost.

    Subclasses must expose: self.status, self.price, self.quantity, self._source.
    """
    STATUS_ORDERED = 'ordered'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUSES = {
        STATUS_ORDERED: 'Bellenen',
        STATUS_COMPLETED: 'Ýerine ýetirilen',
        STATUS_CANCELLED: 'Ýatyrylan',
    }

    @property
    def is_ordered(self) -> bool:
        return self.status == self.STATUS_ORDERED

    @property
    def is_completed(self) -> bool:
        return self.status == self.STATUS_COMPLETED

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.STATUS_CANCELLED

    @property
    def status_display(self) -> str:
        return self.STATUSES.get(self.status, self.status)

    @property
    def name_display(self) -> str:
        return self._source.name

    @property
    def bill_name(self) -> str:
        return self._source.name

    @property
    def bill_note(self) -> str:
        return f"{self.ordered_at.strftime('%d.%m.%Y')} — {self.status_display.lower()}"

    @property
    def price_display(self) -> str:
        return f'{self.price:,.2f}'

    @property
    def total(self):
        return self.price * (self.quantity or 1)

    @property
    def total_display(self) -> str:
        return f'{self.total:,.2f}'


class HospitalizationAnalysisOrder(InpatientOrderMixin, InpatientBillingMixin, db.Model):
    """A lab analysis ordered for a hospitalized patient.

    `combined_analysis_id` remembers that the row came in as part of a panel:
    a panel is expanded into its analyses at ordering, because that is what is
    carried out and what is priced, but the doctor should still see what they
    actually picked.
    """
    __tablename__ = 'hospitalization_analysis_orders'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey('analyses.id'), nullable=False, index=True)
    combined_analysis_id = db.Column(db.Integer, db.ForeignKey('combined_analyses.id'), nullable=True)

    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    note = db.Column(db.String(500), nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=InpatientOrderMixin.STATUS_ORDERED,
                       index=True)
    ordered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    result = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancel_reason = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='analysis_orders')
    analysis = db.relationship('Analysis')
    combined_analysis = db.relationship('CombinedAnalysis')
    ordered_by = db.relationship('User', foreign_keys=[ordered_by_id])
    completed_by = db.relationship('User', foreign_keys=[completed_by_id])
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_id])

    @property
    def _source(self):
        return self.analysis

    def __repr__(self) -> str:
        return f'<HospitalizationAnalysisOrder h={self.hospitalization_id} a={self.analysis_id}>'


class HospitalizationToolOrder(InpatientOrderMixin, InpatientBillingMixin, db.Model):
    """An instrumental study (ultrasound, x-ray, …) ordered for a lying patient.

    `price` is the catalogue's `total_price` for one study and `quantity` counts
    the studies — so one study costs exactly what the price list says. The
    catalogue's own `quantity` is left out of the snapshot on purpose: it
    describes the packaging of the service, not how many were ordered.
    """
    __tablename__ = 'hospitalization_tool_orders'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    tool_id = db.Column(db.Integer, db.ForeignKey('analysis_tools.id'), nullable=False, index=True)

    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    note = db.Column(db.String(500), nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=InpatientOrderMixin.STATUS_ORDERED,
                       index=True)
    ordered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    result = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancel_reason = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='tool_orders')
    tool = db.relationship('AnalysisTool')
    ordered_by = db.relationship('User', foreign_keys=[ordered_by_id])
    completed_by = db.relationship('User', foreign_keys=[completed_by_id])
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_id])

    @property
    def _source(self):
        return self.tool

    def __repr__(self) -> str:
        return f'<HospitalizationToolOrder h={self.hospitalization_id} t={self.tool_id}>'


class HospitalizationBlankOrder(InpatientOrderMixin, InpatientBillingMixin, db.Model):
    """A blank (form) issued for a lying patient. Same lifecycle as an analysis
    order — `result` here holds a note about the issue, since a blank has no
    finding of its own."""
    __tablename__ = 'hospitalization_blank_orders'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    blank_id = db.Column(db.Integer, db.ForeignKey('blanks.id'), nullable=False, index=True)

    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    note = db.Column(db.String(500), nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=InpatientOrderMixin.STATUS_ORDERED,
                       index=True)
    ordered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    result = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancel_reason = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='blank_orders')
    blank = db.relationship('Blank')
    ordered_by = db.relationship('User', foreign_keys=[ordered_by_id])
    completed_by = db.relationship('User', foreign_keys=[completed_by_id])
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_id])

    @property
    def _source(self):
        return self.blank

    def __repr__(self) -> str:
        return f'<HospitalizationBlankOrder h={self.hospitalization_id} b={self.blank_id}>'


class HospitalizationConsultation(InpatientOrderMixin, InpatientBillingMixin, db.Model):
    """A specialist called in to see a lying patient.

    The service comes from the same `DoctorDirection` catalogue the outpatient
    section uses (so it has a price), plus the particular doctor who is asked to
    come. The conclusion is entered by the attending doctor or the head of the
    department — the consultant is not given access to another department's
    case history, they say what they found and the ward writes it down over
    their name.
    """
    __tablename__ = 'hospitalization_consultations'

    id = db.Column(db.Integer, primary_key=True)
    hospitalization_id = db.Column(db.Integer, db.ForeignKey('hospitalizations.id'),
                                   nullable=False, index=True)
    direction_id = db.Column(db.Integer, db.ForeignKey('doctor_directions.id'),
                             nullable=False, index=True)
    # the specialist asked for; kept even after the consultation happened
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_insurance = db.Column(db.Boolean, nullable=False, default=False)

    reason = db.Column(db.String(500), nullable=True)
    payment_method = db.Column(db.String(10), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=InpatientOrderMixin.STATUS_ORDERED,
                       index=True)
    ordered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ordered_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    conclusion = db.Column(db.Text, nullable=True)
    # when the specialist actually saw the patient — not when the note was typed
    performed_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancel_reason = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    hospitalization = db.relationship('Hospitalization', back_populates='consultations')
    direction = db.relationship('DoctorDirection')
    doctor = db.relationship('User', foreign_keys=[doctor_id])
    ordered_by = db.relationship('User', foreign_keys=[ordered_by_id])
    completed_by = db.relationship('User', foreign_keys=[completed_by_id])
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_id])

    @property
    def _source(self):
        return self.direction

    @property
    def quantity(self) -> int:
        """A consultation is one visit — the mixin's totals expect a count."""
        return 1

    @property
    def bill_note(self) -> str:
        return f"{self.doctor.full_name} — {self.status_display.lower()}"

    def __repr__(self) -> str:
        return f'<HospitalizationConsultation h={self.hospitalization_id} d={self.direction_id}>'
