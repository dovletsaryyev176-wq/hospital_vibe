import re
from flask_wtf import FlaskForm
from wtforms import (StringField, SelectField, SubmitField, TextAreaField,
                     DecimalField, IntegerField)
from wtforms.validators import (DataRequired, Length, Optional, NumberRange,
                                Regexp, ValidationError)
from app.models import Hospitalization


PHONE_RE = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')


def valid_phone(value: str) -> bool:
    return bool(PHONE_RE.match(value.strip()))


class HospitalizationForm(FlaskForm):
    """Opened by the department head. Relatives are handled separately in the
    route — the rows are dynamic, so they arrive as parallel form arrays."""

    department_id = SelectField(
        'Bölüm',
        coerce=int,
        validators=[DataRequired(message='Bölümi saýlaň')],
    )
    history_number = StringField(
        'Kesel taryhynyň belgisi',
        validators=[
            DataRequired(message='Kesel taryhynyň belgisini giriziň'),
            Length(max=50, message='50 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: 2026/00123'},
    )
    submit = SubmitField('Ýatyrmak')

    def __init__(self, *args, departments=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.department_id.choices = [(d.id, d.name) for d in (departments or [])]

    def validate_history_number(self, field):
        value = field.data.strip() if field.data else ''
        if not value:
            return
        if Hospitalization.query.filter_by(history_number=value).first():
            raise ValidationError('Bu belgili kesel taryhy eýýäm bar.')


class BedAssignmentForm(FlaskForm):
    """Senior nurse picks a free bed; the room is derived from the bed."""

    bed_id = SelectField(
        'Palata / krowat',
        coerce=int,
        validators=[DataRequired(message='Krowady saýlaň')],
    )
    submit = SubmitField('Bellemek')

    def __init__(self, *args, beds=None, **kwargs):
        super().__init__(*args, **kwargs)
        # beds: list of (bed, room) pairs, already filtered to free ones
        self.bed_id.choices = [(b.id, f'{r.name} / {b.name}') for b, r in (beds or [])]


class DoctorAssignmentForm(FlaskForm):
    """Department head picks the attending doctor from their own department."""

    doctor_id = SelectField(
        'Bejeriji lukman',
        coerce=int,
        validators=[DataRequired(message='Lukmany saýlaň')],
    )
    submit = SubmitField('Bellemek')

    def __init__(self, *args, doctors=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor_id.choices = [
            (d.id, f'{d.full_name}' + (f' · {d.cabinet}' if d.cabinet else ''))
            for d in (doctors or [])
        ]


class DiaryEntryForm(FlaskForm):
    """A doctor's progress note. Every field is optional on its own, but the
    note may not be completely empty."""

    complaints = TextAreaField(
        'Şikaýatlary',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Syrkawyň şikaýatlary'},
    )
    objective = TextAreaField(
        'Obýektiw ýagdaýy',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 3, 'placeholder': 'Umumy ýagdaýy, gözden geçirme'},
    )
    dynamics = TextAreaField(
        'Dinamikasy',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Öňki gün bilen deňeşdirilende'},
    )
    plan = TextAreaField(
        'Meýilnama',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Bejergini dowam etmek, barlaglar'},
    )

    temperature = DecimalField(
        'Temperaturasy (°C)',
        validators=[Optional(), NumberRange(min=30, max=45, message='30-45 °C aralygynda bolmaly')],
        places=1,
        render_kw={'placeholder': '36.6', 'step': '0.1'},
    )
    blood_pressure = StringField(
        'Gan basyşy',
        validators=[
            Optional(),
            Regexp(r'^\d{2,3}/\d{2,3}$', message='Mysal: 120/80'),
        ],
        render_kw={'placeholder': '120/80'},
    )
    pulse = IntegerField(
        'Puls (1 min)',
        validators=[Optional(), NumberRange(min=20, max=300, message='20-300 aralygynda bolmaly')],
        render_kw={'placeholder': '72'},
    )

    submit = SubmitField('Ýatda saklamak')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        texts = (self.complaints.data, self.objective.data, self.dynamics.data, self.plan.data)
        if not any(t and t.strip() for t in texts):
            self.objective.errors.append('Iň azyndan bir meýdany dolduryň.')
            return False
        return True
