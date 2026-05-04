from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError
from app.models import Patient


class PatientForm(FlaskForm):
    full_name = StringField(
        'FAA',
        validators=[
            DataRequired(message='FAA giriziň'),
            Length(min=2, max=150, message='FAA 2-150 siwmol arasynda bolmaly'),
        ],
        render_kw={'placeholder': 'Familiýasy, ady, atasynyň ady'},
    )
    birth_year = IntegerField(
        'Doglan ýyly',
        validators=[
            DataRequired(message='Doglan ýyly giriziň'),
            NumberRange(min=1900, max=datetime.now().year,
                        message=f'Doglan ýyl 1900 - {datetime.now().year} arasynda bolmaly'),
        ],
        render_kw={'placeholder': 'Mysal: 1987'},
    )
    citizenship = StringField(
        'Raýatlylyk',
        validators=[
            DataRequired(message='Raýatlylygy giriziň'),
            Length(max=100, message='100 siwmoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: Türkmenistan'},
    )
    home_address = TextAreaField(
        'Öý salgysy',
        validators=[
            DataRequired(message='Öý salgyny giriziň'),
            Length(max=255, message='255 siwmoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Şäher köçe jaý otag', 'rows': 2},
    )
    passport_number = StringField(
        'Pasport belgisi',
        validators=[
            DataRequired(message='Pasport belgisini giriziň'),
            Length(max=50, message='50 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Pasport belgisi'},
    )
    insurance_number = StringField(
        'Ätiýaçlandyryş belgisi',
        validators=[
            Optional(),
            Length(max=50, message='50 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Ätiýaçlandyryş belgisi (mejbury däl)'},
    )
    submit = SubmitField('Сохранить')

    def __init__(self, *args, editing_patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._editing_patient = editing_patient

    def validate_passport_number(self, field):
        existing = Patient.query.filter_by(passport_number=field.data.strip()).first()
        if existing and (self._editing_patient is None or existing.id != self._editing_patient.id):
            raise ValidationError('Bu pasport belgili syrkaw eýýäm hasaba alnan.')

    def validate_insurance_number(self, field):
        if not field.data or not field.data.strip():
            return
        existing = Patient.query.filter_by(insurance_number=field.data.strip()).first()
        if existing and (self._editing_patient is None or existing.id != self._editing_patient.id):
            raise ValidationError('Bu ätiýaçlandyryş belgili syrkaw eýýäm hasaba alnan.')
