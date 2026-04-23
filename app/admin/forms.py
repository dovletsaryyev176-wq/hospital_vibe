import re
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, PasswordField, DecimalField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError, Regexp
from app.models import User


PHONE_RE = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')


def validate_phone(form, field):
    if field.data and not PHONE_RE.match(field.data.strip()):
        raise ValidationError('Введите корректный номер телефона.')


def _nullable_int(value):
    """Coerce that maps None/''/0 → 0 to avoid coercion errors on optional FK fields."""
    if value is None or value == '':
        return 0
    return int(value)


class DirectionForm(FlaskForm):
    name = StringField(
        'Наименование',
        validators=[
            DataRequired(message='Введите наименование направления'),
            Length(max=150, message='Не более 150 символов'),
        ],
        render_kw={'placeholder': 'Например: Терапия'},
    )
    submit = SubmitField('Сохранить')

    def __init__(self, *args, editing_direction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_direction = editing_direction

    def validate_name(self, field):
        from app.models import DoctorDirection
        existing = DoctorDirection.query.filter(
            DoctorDirection.name.ilike(field.data.strip())
        ).first()
        if existing and (self._editing_direction is None or existing.id != self._editing_direction.id):
            raise ValidationError('Направление с таким наименованием уже существует.')


class UserForm(FlaskForm):
    full_name = StringField(
        'ФИО',
        validators=[
            DataRequired(message='Введите ФИО'),
            Length(min=2, max=150, message='ФИО должно быть от 2 до 150 символов'),
        ],
        render_kw={'placeholder': 'Фамилия Имя Отчество'},
    )
    username = StringField(
        'Логин',
        validators=[
            DataRequired(message='Введите логин'),
            Length(min=3, max=50, message='Логин должен быть от 3 до 50 символов'),
            Regexp(r'^[\w]+$', message='Логин может содержать только буквы, цифры и знак подчёркивания'),
        ],
        render_kw={'placeholder': 'Логин для входа'},
    )
    role = SelectField(
        'Роль',
        choices=[
            ('', '— Выберите роль —'),
            ('administrator', 'Администратор'),
            ('registrar', 'Регистратор'),
            ('doctor', 'Врач'),
            ('analysis_responsible', 'Ответственный по анализам'),
            ('cashier', 'Кассир'),
        ],
        validators=[DataRequired(message='Выберите роль')],
    )
    phone_number = StringField(
        'Телефон',
        validators=[
            DataRequired(message='Введите телефонный номер'),
            validate_phone,
        ],
        render_kw={'placeholder': '+7 (___) ___-__-__'},
    )
    cabinet = StringField(
        'Кабинет',
        validators=[Optional(), Length(max=20, message='Номер кабинета не более 20 символов')],
        render_kw={'placeholder': 'Например: 101'},
    )
    direction_id = SelectField(
        'Направление врача',
        coerce=_nullable_int,
        validators=[Optional()],
    )
    password = PasswordField(
        'Пароль',
        validators=[Optional(), Length(min=6, message='Пароль не менее 6 символов')],
        render_kw={'placeholder': 'Не менее 6 символов'},
    )
    submit = SubmitField('Сохранить')

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
        choices = [(0, '— Не указано —')]

        # When editing, keep the current direction even if it's been blocked
        if self._editing_user and self._editing_user.direction_id:
            current = self._editing_user.direction
            if current and not current.is_active:
                choices.append((current.id, f'{current.name} [отключено]'))
                choices += [(d.id, d.name) for d in active if d.id != current.id]
            else:
                choices += [(d.id, d.name) for d in active]
        else:
            choices += [(d.id, d.name) for d in active]

        self.direction_id.choices = choices

    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data.strip()).first()
        if existing and (self._editing_user is None or existing.id != self._editing_user.id):
            raise ValidationError('Пользователь с таким логином уже существует.')

    def validate_password(self, field):
        if self._editing_user is None and not field.data:
            raise ValidationError('Пароль обязателен при создании пользователя.')


class AnalysisForm(FlaskForm):
    name = StringField(
        'Наименование',
        validators=[
            DataRequired(message='Введите наименование анализа'),
            Length(max=200, message='Наименование не более 200 символов'),
        ],
        render_kw={'placeholder': 'Название анализа'},
    )
    price = DecimalField(
        'Цена (руб.)',
        validators=[
            DataRequired(message='Введите цену'),
            NumberRange(min=0, message='Цена не может быть отрицательной'),
        ],
        places=2,
        render_kw={'placeholder': '0.00', 'step': '0.01', 'min': '0'},
    )
    responsible_id = SelectField(
        'Ответственный по анализам',
        coerce=int,
        validators=[DataRequired(message='Выберите ответственного')],
    )
    submit = SubmitField('Сохранить')

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
        choices = [(0, '— Выберите ответственного —')]

        if self._editing_analysis and self._editing_analysis.responsible:
            current = self._editing_analysis.responsible
            if not current.is_active:
                choices.append((current.id, f'{current.full_name} [заблокирован]'))
                choices += [(u.id, u.full_name) for u in active_users]
            else:
                choices += [(u.id, u.full_name) for u in active_users]
        else:
            choices += [(u.id, u.full_name) for u in active_users]

        self.responsible_id.choices = choices

    def validate_responsible_id(self, field):
        if not field.data:
            raise ValidationError('Выберите ответственного по анализам.')
