from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError
from app.models import Patient


class PatientForm(FlaskForm):
    full_name = StringField(
        'ФИО',
        validators=[
            DataRequired(message='Введите ФИО'),
            Length(min=2, max=150, message='ФИО должно быть от 2 до 150 символов'),
        ],
        render_kw={'placeholder': 'Фамилия Имя Отчество'},
    )
    birth_year = IntegerField(
        'Год рождения',
        validators=[
            DataRequired(message='Введите год рождения'),
            NumberRange(min=1900, max=datetime.utcnow().year,
                        message=f'Год рождения должен быть от 1900 до {datetime.utcnow().year}'),
        ],
        render_kw={'placeholder': 'Например: 1985'},
    )
    citizenship = StringField(
        'Гражданство',
        validators=[
            DataRequired(message='Введите гражданство'),
            Length(max=100, message='Не более 100 символов'),
        ],
        render_kw={'placeholder': 'Например: Россия'},
    )
    home_address = TextAreaField(
        'Домашний адрес',
        validators=[
            DataRequired(message='Введите домашний адрес'),
            Length(max=255, message='Не более 255 символов'),
        ],
        render_kw={'placeholder': 'Город, улица, дом, квартира', 'rows': 2},
    )
    insurance_number = StringField(
        'Номер медицинского страхования',
        validators=[
            DataRequired(message='Введите номер страхования'),
            Length(max=50, message='Не более 50 символов'),
        ],
        render_kw={'placeholder': 'Номер полиса ОМС'},
    )
    submit = SubmitField('Сохранить')

    def __init__(self, *args, editing_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_patient = editing_patient

    def validate_insurance_number(self, field):
        existing = Patient.query.filter_by(insurance_number=field.data.strip()).first()
        if existing and (self._editing_patient is None or existing.id != self._editing_patient.id):
            raise ValidationError('Пациент с таким номером страхования уже существует.')
