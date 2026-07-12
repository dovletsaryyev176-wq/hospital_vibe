import re
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SelectMultipleField, PasswordField, DecimalField, IntegerField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError, Regexp
from app.models import User, Analysis, AnalysisTool, Blank, AnalysisToolCategory, AnalysisToolSubcategory, DoctorDirectionCategory


PHONE_RE = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')


def validate_phone(form, field):
    if field.data and not PHONE_RE.match(field.data.strip()):
        raise ValidationError('Dogry telefon belgisini giriziň.')


def _nullable_int(value):
    """Coerce that maps None/''/0 → 0 to avoid coercion errors on optional FK fields."""
    if value is None or value == '':
        return 0
    return int(value)


class DirectionForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Ugruň adyny giriziň'),
            Length(max=150, message='150 belgiden geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: maşgala lukmany'},
    )
    price = DecimalField(
        'Bahasy (Manat)',
        validators=[
            DataRequired(message='Bahany giriziň'),
            NumberRange(min=0, message='Baha otrisatel bolup bilmeýär'),
        ],
        places=2,
        render_kw={'placeholder': '0.00'},
    )
    is_insurance = BooleanField('Ätiýaçlandyryş')
    category_id = SelectField('Kategoriýa (islege görä)', coerce=int, validators=[Optional()])
    analysis_ids = SelectMultipleField(
        'Baglanyşykly analizler',
        coerce=int,
        validators=[Optional()],
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_direction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_direction = editing_direction
        self._build_analysis_choices()
        self._build_category_choices()

    def _build_category_choices(self):
        cats = DoctorDirectionCategory.query.filter_by(is_active=True).order_by(DoctorDirectionCategory.name).all()
        choices = [(0, '— Kategoriýa saýlaň (islege görä) —')]
        if self._editing_direction and self._editing_direction.category_id:
            current = self._editing_direction.category
            if current and not current.is_active:
                choices.append((current.id, f'{current.name} [bloklanan]'))
        choices += [(c.id, c.name) for c in cats]
        self.category_id.choices = choices

    def _build_analysis_choices(self):
        active = (
            Analysis.query
            .filter_by(is_active=True)
            .order_by(Analysis.name)
            .all()
        )
        choices = [(a.id, a.name) for a in active]

        if self._editing_direction:
            blocked = [
                a for a in self._editing_direction.analyses
                if not a.is_active
            ]
            choices = [(a.id, f'{a.name} [bloklanan]') for a in blocked] + choices

        self.analysis_ids.choices = choices

    def validate_name(self, field):
        from app.models import DoctorDirection
        existing = DoctorDirection.query.filter(
            DoctorDirection.name.ilike(field.data.strip())
        ).first()
        if existing and (self._editing_direction is None or existing.id != self._editing_direction.id):
            raise ValidationError('Bu atly ugur eýýäm hasaba alnan.')


class DirectionCategoryForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Kategoriýanyň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Kategoriýanyň ady'},
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_category = editing_category

    def validate_name(self, field):
        existing = DoctorDirectionCategory.query.filter(
            DoctorDirectionCategory.name.ilike(field.data.strip())
        ).first()
        if existing and (self._editing_category is None or existing.id != self._editing_category.id):
            raise ValidationError('Bu atly kategoriýa eýýäm hasaba alnan.')


class UserForm(FlaskForm):
    full_name = StringField(
        'FAA',
        validators=[
            DataRequired(message='FAA giriziň'),
            Length(min=2, max=150, message='FAA 2-150 belgi arasynda bolmaly'),
        ],
        render_kw={'placeholder': 'Familiýasy Ady Atasynyň ady'},
    )
    username = StringField(
        'Ulanyjy ady',
        validators=[
            DataRequired(message='Ulanyjy ady giriziň'),
            Length(min=3, max=50, message='Ulanyjy ady 3-50 belgi arasynda bolmaly'),
            Regexp(r'^[\w]+$', message='Ulanyjy adynda diňe harp, san we aşayk çyzgy bolup bilýar'),
        ],
        render_kw={'placeholder': 'Ulanyjy ady'},
    )
    role = SelectField(
        'Roly',
        choices=[
            ('', '— Roly saýlaň —'),
            ('administrator', 'Dolandyryjy'),
            ('registrar', 'Kabulhana'),
            ('doctor', 'Lukman'),
            ('analysis_responsible', 'Analiz boýunça jogapkär'),
            ('cashier', 'Kassir'),
            ('senior_cashier', 'Uly kassir'),
        ],
        validators=[DataRequired(message='Roly saýlaň')],
    )
    phone_number = StringField(
        'Telefon',
        validators=[
            DataRequired(message='Telefon belgini giriziň'),
            validate_phone,
        ],
        render_kw={'placeholder': '+993 (___) ___-__-__'},
    )
    cabinet = StringField(
        'Otag',
        validators=[Optional(), Length(max=20, message='Otag belgisi 20 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Mysal: 101'},
    )
    direction_ids = SelectMultipleField(
        'Lukmanyň ugurlary',
        coerce=int,
        validators=[Optional()],
    )
    password = PasswordField(
        'Gizlin belgi',
        validators=[Optional(), Length(min=6, message='Gizlin belgi iň az 6 siwmoldan ybarat bolmaly')],
        render_kw={'placeholder': 'Iň az 6 simwol bolmaly'},
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_user = editing_user
        self._build_direction_choices()

    def _build_direction_choices(self):
        from app.models import DoctorDirection
        active = (
            DoctorDirection.query
            .filter_by(is_active=True)
            .order_by(DoctorDirection.name)
            .all()
        )
        choices = [(d.id, d.name) for d in active]

        if self._editing_user:
            active_ids = {d.id for d in active}
            for d in self._editing_user.directions:
                if not d.is_active and d.id not in active_ids:
                    choices.insert(0, (d.id, f'{d.name} [bloklanan]'))

        self.direction_ids.choices = choices

    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data.strip()).first()
        if existing and (self._editing_user is None or existing.id != self._editing_user.id):
            raise ValidationError('Bu atly ulanyjy eýýäm hasaba alnan.')

    def validate_password(self, field):
        if self._editing_user is None and not field.data:
            raise ValidationError('Ulanyjynyň gizlin belgisi hökmanydyr.')


class AnalysisForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Analiziň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Analiziň ady'},
    )
    price = DecimalField(
        'Bahasy (manat)',
        validators=[
            DataRequired(message='Bahany giriziň'),
            NumberRange(min=0, message='Baha otrisatel bolup bilmeýär'),
        ],
        places=2,
        render_kw={'placeholder': '0.00', 'step': '0.01', 'min': '0'},
    )
    responsible_id = SelectField(
        'Analizler boýunça jogapkär',
        coerce=int,
        validators=[DataRequired(message='Jogapkäri saýlaň')],
    )
    is_insurance = BooleanField('Ätiýaçlandyryş')
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_analysis=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_analysis = editing_analysis
        self._build_responsible_choices()

    def _build_responsible_choices(self):
        active_users = (
            User.query
            .filter_by(role='analysis_responsible', is_active=True)
            .order_by(User.full_name)
            .all()
        )
        choices = [(0, '— Jogapkäri saýlaň —')]

        if self._editing_analysis and self._editing_analysis.responsible:
            current = self._editing_analysis.responsible
            if not current.is_active:
                choices.append((current.id, f'{current.full_name} [bloklanan]'))
                choices += [(u.id, u.full_name) for u in active_users]
            else:
                choices += [(u.id, u.full_name) for u in active_users]
        else:
            choices += [(u.id, u.full_name) for u in active_users]

        self.responsible_id.choices = choices

    def validate_responsible_id(self, field):
        if not field.data:
            raise ValidationError('Analiz boýunça jogapkäri saýlaň.')


class CombinedAnalysisForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Kombinlenen analiziň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Kombinlened analiziň ady'},
    )
    analysis_ids = SelectMultipleField(
        'Analizler',
        coerce=int,
        validators=[DataRequired(message='Iň az bir analiz saýlaň')],
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_combined=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_combined = editing_combined
        self._build_analysis_choices()

    def _build_analysis_choices(self):
        active = (
            Analysis.query
            .filter_by(is_active=True)
            .order_by(Analysis.name)
            .all()
        )
        choices = [(a.id, a.name) for a in active]

        if self._editing_combined:
            active_ids = {a.id for a in active}
            for a in self._editing_combined.analyses:
                if not a.is_active and a.id not in active_ids:
                    choices.insert(0, (a.id, f'{a.name} [bloklanan]'))

        self.analysis_ids.choices = choices

    def validate_name(self, field):
        from app.models import CombinedAnalysis
        existing = CombinedAnalysis.query.filter(
            CombinedAnalysis.name.ilike(field.data.strip())
        ).first()
        if existing and (self._editing_combined is None or existing.id != self._editing_combined.id):
            raise ValidationError('Bu atly kombinlened analiz eýýäm hasaba alnan.')

    def validate_analysis_ids(self, field):
        if not field.data:
            raise ValidationError('Iň az bir analiz saýlaň.')


class AnalysisToolForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Serişdäniň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Serişdäniň ady'},
    )
    quantity = IntegerField(
        'Mukdary',
        validators=[
            DataRequired(message='Mukdary giriziň'),
            NumberRange(min=1, message='Mukdar iň az 1 bolmaly'),
        ],
        render_kw={'placeholder': '1', 'min': '1'},
    )
    is_insurance = BooleanField('Ätiýaçlandyryş')
    total_price = DecimalField(
        'Jemi bahasy (manat)',
        validators=[
            DataRequired(message='Jemi bahany giriziň'),
            NumberRange(min=0, message='Baha otrisatel bolup bilmeýär'),
        ],
        places=2,
        render_kw={'placeholder': '0.00', 'step': '0.01', 'min': '0'},
    )
    analysis_ids = SelectMultipleField(
        'Analizler',
        coerce=int,
    )
    category_id = SelectField('Kategoriýa (islege görä)', coerce=int, validators=[Optional()])
    subcategory_id = SelectField('Kiçi kategoriýa (islege görä)', coerce=int, validators=[Optional()])
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_tool=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_tool = editing_tool
        self._build_analysis_choices()
        self._build_category_choices()
        self._build_subcategory_choices()

    def _build_analysis_choices(self):
        active = (
            Analysis.query
            .filter_by(is_active=True)
            .order_by(Analysis.name)
            .all()
        )
        choices = [(a.id, a.name) for a in active]

        if self._editing_tool:
            blocked = [
                a for a in self._editing_tool.analyses
                if not a.is_active
            ]
            choices = [(a.id, f'{a.name} [bloklanan]') for a in blocked] + choices

        self.analysis_ids.choices = choices

    def validate_analysis_ids(self, field):
        if not field.data:
            raise ValidationError('Iň bolmanda 1 analizi saýlaň.')

    def _build_category_choices(self):
        cats = AnalysisToolCategory.query.filter_by(is_active=True).order_by(AnalysisToolCategory.name).all()
        self.category_id.choices = [(0, '— Kategoriýa saýlaň (islege görä) —')] + [(c.id, c.name) for c in cats]

    def _build_subcategory_choices(self):
        subs = AnalysisToolSubcategory.query.filter_by(is_active=True).order_by(AnalysisToolSubcategory.name).all()
        self.subcategory_id.choices = [(0, '— Kiçi kategoriýa saýlaň (islege görä) —')] + [(s.id, s.name) for s in subs]


class AnalysisToolCategoryForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Kategoriýanyň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Kategoriýanyň ady'},
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_category = editing_category

    def validate_name(self, field):
        existing = AnalysisToolCategory.query.filter(
            AnalysisToolCategory.name.ilike(field.data.strip())
        ).first()
        if existing and (self._editing_category is None or existing.id != self._editing_category.id):
            raise ValidationError('Bu atly kategoriýa eýýäm hasaba alnan.')


class AnalysisToolSubcategoryForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Kiçi kategoriýanyň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Kiçi kategoriýanyň ady'},
    )
    category_id = SelectField('Kategoriýa', coerce=int, validators=[Optional()])
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_subcategory=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_subcategory = editing_subcategory
        self._build_category_choices()

    def _build_category_choices(self):
        cats = AnalysisToolCategory.query.filter_by(is_active=True).order_by(AnalysisToolCategory.name).all()
        choices = [(0, '— Kategoriýa saýlaň —')]
        if self._editing_subcategory and self._editing_subcategory.category_id:
            current = self._editing_subcategory.category
            if current and not current.is_active:
                choices.append((current.id, f'{current.name} [bloklanan]'))
        choices += [(c.id, c.name) for c in cats]
        self.category_id.choices = choices

    def validate_category_id(self, field):
        if not field.data:
            raise ValidationError('Kiçi kategoriýa üçin kategoriýa saýlamak hökmany.')


class BlankForm(FlaskForm):
    name = StringField(
        'Ady',
        validators=[
            DataRequired(message='Blankyň adyny giriziň'),
            Length(max=200, message='Ady 200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Blankyň ady'},
    )
    quantity = IntegerField(
        'Mukdary',
        validators=[
            DataRequired(message='Mukdary giriziň'),
            NumberRange(min=1, message='Mukdar iň az 1 bolmaly'),
        ],
        render_kw={'placeholder': '1', 'min': '1'},
    )
    is_insurance = BooleanField('Ätiýaçlandyryş')
    total_price = DecimalField(
        'Jemi bahasy (manat)',
        validators=[
            DataRequired(message='Jemi bahany giriziň'),
            NumberRange(min=0, message='Baha otrisatel bolup bilmeýär'),
        ],
        places=2,
        render_kw={'placeholder': '0.00', 'step': '0.01', 'min': '0'},
    )
    analysis_ids = SelectMultipleField(
        'Analizler',
        coerce=int,
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, editing_blank=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_blank = editing_blank
        self._build_analysis_choices()

    def _build_analysis_choices(self):
        active = (
            Analysis.query
            .filter_by(is_active=True)
            .order_by(Analysis.name)
            .all()
        )
        choices = [(a.id, a.name) for a in active]

        if self._editing_blank:
            blocked = [
                a for a in self._editing_blank.analyses
                if not a.is_active
            ]
            choices = [(a.id, f'{a.name} [bloklanan]') for a in blocked] + choices

        self.analysis_ids.choices = choices
