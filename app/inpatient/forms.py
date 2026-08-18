import re
from datetime import date, datetime
from flask_wtf import FlaskForm
from wtforms import (StringField, SelectField, SelectMultipleField, SubmitField, TextAreaField,
                     DecimalField, IntegerField, DateField, DateTimeLocalField)
from wtforms.validators import (DataRequired, Length, Optional, NumberRange,
                                Regexp, ValidationError)
from app.models import (Hospitalization, HospitalizationMedicationOrder, MedicineStockMovement,
                        HospitalizationDiagnosis, HospitalizationOperation, PatientAllergy)


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
    # A stay is opened *because of* something — the preliminary diagnosis is
    # required at admission and may be revised later.
    diagnosis = StringField(
        'Çaklama diagnoz',
        validators=[
            DataRequired(message='Çaklama diagnozy giriziň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: Ýiti appendisit'},
    )
    diagnosis_code = StringField(
        'HKK-10 kody',
        validators=[Optional(), Length(max=20, message='20 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Mysal: K35.8'},
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


class TransferForm(FlaskForm):
    """Moving a running stay to another department.

    The reason is required: a patient who turns up in another ward with nothing
    said about why is exactly what the transfer record exists to prevent.
    """

    department_id = SelectField(
        'Geçirilýän bölüm',
        coerce=int,
        validators=[DataRequired(message='Bölümi saýlaň')],
    )
    reason = TextAreaField(
        'Geçirmegiň sebäbi',
        validators=[
            DataRequired(message='Geçirmegiň sebäbini ýazyň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 3,
                   'placeholder': 'Mysal: ýagdaýy agyrlaşdy, reanimasiýa bejergisi zerur'},
    )
    submit = SubmitField('Geçirmek')

    def __init__(self, *args, departments=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.department_id.choices = [(d.id, d.name) for d in (departments or [])]


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


def _medicine_choices(medicines):
    return [(m.id, f'{m.name} · {m.unit_display}') for m in (medicines or [])]


class StockReceiptForm(FlaskForm):
    """Senior nurse books drugs into their ward's store."""

    medicine_id = SelectField(
        'Derman',
        coerce=int,
        validators=[DataRequired(message='Dermany saýlaň')],
    )
    quantity = DecimalField(
        'Mukdary',
        validators=[
            DataRequired(message='Mukdaryny giriziň'),
            NumberRange(min=0.01, message='Mukdary 0-dan uly bolmaly'),
        ],
        places=2,
        render_kw={'placeholder': '0', 'step': '0.01', 'min': '0.01'},
    )
    note = StringField(
        'Bellik',
        validators=[Optional(), Length(max=500, message='Bellik 500 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Nireden alyndy, resminama belgisi'},
    )
    submit = SubmitField('Girdejini ýazmak')

    def __init__(self, *args, medicines=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.medicine_id.choices = _medicine_choices(medicines)


class StockAdjustForm(FlaskForm):
    """Write-off (spoilage, expiry) or a correction upwards. A note is required
    either way — an unexplained balance change is what the journal exists to
    prevent."""

    medicine_id = SelectField(
        'Derman',
        coerce=int,
        validators=[DataRequired(message='Dermany saýlaň')],
    )
    kind = SelectField(
        'Amalyň görnüşi',
        validators=[DataRequired(message='Amalyň görnüşini saýlaň')],
        choices=[
            (MedicineStockMovement.KIND_WRITEOFF, 'Hasapdan öçürmek (−)'),
            (MedicineStockMovement.KIND_CORRECTION, 'Düzediş — goşmak (+)'),
        ],
    )
    quantity = DecimalField(
        'Mukdary',
        validators=[
            DataRequired(message='Mukdaryny giriziň'),
            NumberRange(min=0.01, message='Mukdary 0-dan uly bolmaly'),
        ],
        places=2,
        render_kw={'placeholder': '0', 'step': '0.01', 'min': '0.01'},
    )
    note = StringField(
        'Sebäbi',
        validators=[
            DataRequired(message='Sebäbini ýazyň'),
            Length(max=500, message='Sebäbi 500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: möhleti geçen, döwülen'},
    )
    submit = SubmitField('Ýazmak')

    def __init__(self, *args, medicines=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.medicine_id.choices = _medicine_choices(medicines)


class MedicationOrderForm(FlaskForm):
    """A doctor's drug order. `dose` is the clinical instruction the patient
    gets, `quantity_per_dose` is what the nurse takes off the shelf for it —
    they are not the same number and must not be merged."""

    medicine_id = SelectField(
        'Derman',
        coerce=int,
        validators=[DataRequired(message='Dermany saýlaň')],
    )
    dose = StringField(
        'Dozasy',
        validators=[
            DataRequired(message='Dozasyny giriziň'),
            Length(max=100, message='100 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: 500 mg'},
    )
    route = SelectField(
        'Kabul ediş ýoly',
        validators=[DataRequired(message='Kabul ediş ýoluny saýlaň')],
    )
    frequency = StringField(
        'Kabul ediş tertibi',
        validators=[Optional(), Length(max=100, message='100 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Mysal: günde 3 gezek'},
    )
    quantity_per_dose = DecimalField(
        'Bir gezekde berilýän mukdary',
        validators=[
            DataRequired(message='Mukdaryny giriziň'),
            NumberRange(min=0.01, message='Mukdary 0-dan uly bolmaly'),
        ],
        places=2,
        default=1,
        render_kw={'placeholder': '1', 'step': '0.01', 'min': '0.01'},
    )
    planned_end_at = DateField(
        'Meýilleşdirilen soňy',
        validators=[Optional()],
    )
    note = TextAreaField(
        'Bellik',
        validators=[Optional(), Length(max=500, message='Bellik 500 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Bellik (islege görä)'},
    )
    submit = SubmitField('Bellemek')

    def __init__(self, *args, medicines=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.medicine_id.choices = _medicine_choices(medicines)
        self.route.choices = list(HospitalizationMedicationOrder.ROUTES.items())

    def validate_planned_end_at(self, field):
        if field.data and field.data < date.today():
            raise ValidationError('Geçen gün bolup bilmeýär.')


class DiagnosisForm(FlaskForm):
    """Adding or revising a diagnosis on a stay. Revising writes a new row of
    the same kind rather than overwriting — the history stays readable."""

    kind = SelectField(
        'Diagnozyň görnüşi',
        validators=[DataRequired(message='Diagnozyň görnüşini saýlaň')],
    )
    text = StringField(
        'Diagnoz',
        validators=[
            DataRequired(message='Diagnozy giriziň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: Ýiti appendisit'},
    )
    code = StringField(
        'HKK-10 kody',
        validators=[Optional(), Length(max=20, message='20 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Mysal: K35.8'},
    )
    note = TextAreaField(
        'Bellik',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Esaslandyrma, goşmaça maglumat'},
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, allowed_kinds=None, **kwargs):
        super().__init__(*args, **kwargs)
        kinds = allowed_kinds or list(HospitalizationDiagnosis.KINDS)
        self.kind.choices = [(k, HospitalizationDiagnosis.KINDS[k]) for k in kinds]


class DischargeForm(FlaskForm):
    """Closing a stay. The final diagnosis and the outcome are mandatory —
    a discharge that records neither says nothing about what happened."""

    outcome = SelectField(
        'Netijesi',
        validators=[DataRequired(message='Netijesini saýlaň')],
    )
    diagnosis = StringField(
        'Jemleýji diagnoz',
        validators=[
            DataRequired(message='Jemleýji diagnozy giriziň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: Ýiti flegmonoz appendisit'},
    )
    diagnosis_code = StringField(
        'HKK-10 kody',
        validators=[Optional(), Length(max=20, message='20 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Mysal: K35.8'},
    )
    epicrisis = TextAreaField(
        'Epikriz',
        validators=[
            DataRequired(message='Epikrizi ýazyň'),
            Length(max=8000, message='8000 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 6,
                   'placeholder': 'Ýatyrylyş sebäbi, geçirilen barlaglar we bejergi, '
                                  'ýagdaýyň dinamikasy, çykarylanda ýagdaýy'},
    )
    recommendations = TextAreaField(
        'Maslahatlar',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 3, 'placeholder': 'Öý režimi, dermanlar, gaýtadan barlag'},
    )
    submit = SubmitField('Çykarmak')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcome.choices = list(Hospitalization.OUTCOMES.items())


class VitalRecordForm(FlaskForm):
    """The ward nurse's round of measurements. Every field is optional on its
    own, but a record with nothing measured is not a record."""

    measured_at = DateTimeLocalField(
        'Ölçenen wagty',
        validators=[DataRequired(message='Ölçenen wagtyny giriziň')],
        format='%Y-%m-%dT%H:%M',
    )
    temperature = DecimalField(
        'Temperaturasy (°C)',
        validators=[Optional(), NumberRange(min=30, max=45, message='30-45 °C aralygynda bolmaly')],
        places=1,
        render_kw={'placeholder': '36.6', 'step': '0.1'},
    )
    pulse = IntegerField(
        'Puls (1 min)',
        validators=[Optional(), NumberRange(min=20, max=300, message='20-300 aralygynda bolmaly')],
        render_kw={'placeholder': '72'},
    )
    systolic = IntegerField(
        'Ýokarky basyş',
        validators=[Optional(), NumberRange(min=40, max=300, message='40-300 aralygynda bolmaly')],
        render_kw={'placeholder': '120'},
    )
    diastolic = IntegerField(
        'Aşaky basyş',
        validators=[Optional(), NumberRange(min=20, max=200, message='20-200 aralygynda bolmaly')],
        render_kw={'placeholder': '80'},
    )
    respiratory_rate = IntegerField(
        'Dem alşy (1 min)',
        validators=[Optional(), NumberRange(min=5, max=80, message='5-80 aralygynda bolmaly')],
        render_kw={'placeholder': '16'},
    )
    note = StringField(
        'Bellik',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Bellik (islege görä)'},
    )
    submit = SubmitField('Ýazmak')

    def validate_measured_at(self, field):
        if field.data and field.data > datetime.now():
            raise ValidationError('Geljekki wagty görkezip bolmaýar.')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False

        measured = (self.temperature.data, self.pulse.data, self.systolic.data,
                    self.diastolic.data, self.respiratory_rate.data)
        if all(v is None for v in measured):
            self.temperature.errors.append('Iň azyndan bir ölçegi giriziň.')
            return False

        # a pressure is a pair — one half of it is not a reading
        if (self.systolic.data is None) != (self.diastolic.data is None):
            self.systolic.errors.append('Basyşyň iki sanyny hem giriziň.')
            return False
        if (self.systolic.data is not None and self.diastolic.data is not None
                and self.diastolic.data >= self.systolic.data):
            self.diastolic.errors.append('Aşaky basyş ýokarkydan kiçi bolmaly.')
            return False

        return True


class OperationForm(FlaskForm):
    """Planning or writing up an operation. `performed_at` is what decides the
    status: filled in means it happened, empty means it is still planned."""

    operation_id = SelectField(
        'Operasiýa',
        coerce=int,
        validators=[DataRequired(message='Operasiýany saýlaň')],
    )
    surgeon_id = SelectField(
        'Hirurg',
        coerce=int,
        validators=[DataRequired(message='Hirurgy saýlaň')],
    )
    anesthesiologist_id = SelectField(
        'Anesteziolog',
        coerce=int,
        validators=[Optional()],
    )
    assistant_ids = SelectMultipleField('Kömekçiler', coerce=int)
    anesthesia = SelectField(
        'Agyrsyzlandyrma',
        validators=[DataRequired(message='Agyrsyzlandyrmany saýlaň')],
    )
    planned_at = DateTimeLocalField(
        'Meýilleşdirilen wagty',
        validators=[Optional()],
        format='%Y-%m-%dT%H:%M',
    )
    performed_at = DateTimeLocalField(
        'Geçirilen wagty',
        validators=[Optional()],
        format='%Y-%m-%dT%H:%M',
    )
    indication = StringField(
        'Görkezme',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Operasiýa üçin görkezme'},
    )
    protocol = TextAreaField(
        'Operasiýanyň beýany',
        validators=[Optional(), Length(max=8000, message='8000 simwoldan geçmeli däl')],
        render_kw={'rows': 5, 'placeholder': 'Operasiýanyň gidişi'},
    )
    complications = StringField(
        'Gaýra üzülmeler',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Bolmadyk bolsa boş goýuň'},
    )
    submit = SubmitField('Ýatda saklamak')

    def __init__(self, *args, operations=None, medics=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.operation_id.choices = [(o.id, o.name) for o in (operations or [])]
        medic_choices = [(m.id, m.full_name) for m in (medics or [])]
        self.surgeon_id.choices = medic_choices
        self.anesthesiologist_id.choices = [(0, '— Görkezilmedik —')] + medic_choices
        self.assistant_ids.choices = medic_choices
        self.anesthesia.choices = list(HospitalizationOperation.ANESTHESIA.items())

    def validate_performed_at(self, field):
        if field.data and field.data > datetime.now():
            raise ValidationError('Geljekki wagty geçirilen diýip bellenip bilinmeýär.')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if not self.planned_at.data and not self.performed_at.data:
            self.planned_at.errors.append(
                'Meýilleşdirilen ýa-da geçirilen wagtyň biri görkezilmeli.')
            return False
        # the surgeon cannot assist themselves
        if self.surgeon_id.data in (self.assistant_ids.data or []):
            self.assistant_ids.errors.append('Hirurg özüne kömekçi bolup bilmeýär.')
            return False
        return True


class OperationCancelForm(FlaskForm):
    """Calling off a planned operation. A reason is required — a plan that
    silently disappears is indistinguishable from one that was forgotten."""

    reason = StringField(
        'Ýatyrmagyň sebäbi',
        validators=[
            DataRequired(message='Sebäbini ýazyň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: syrkawyň ýagdaýy rugsat bermedi'},
    )
    submit = SubmitField('Ýatyrmak')


class AdmissionExamForm(FlaskForm):
    """The opening document of the case history. Complaints, the history of the
    illness and the objective status are mandatory — an examination missing any
    of the three is not one."""

    complaints = TextAreaField(
        'Şikaýatlary',
        validators=[
            DataRequired(message='Şikaýatlaryny ýazyň'),
            Length(max=8000, message='8000 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 3, 'placeholder': 'Syrkawyň ýatyrylanda şikaýatlary'},
    )
    anamnesis_morbi = TextAreaField(
        'Keseliň anamnezi',
        validators=[
            DataRequired(message='Keseliň anamnezini ýazyň'),
            Length(max=8000, message='8000 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 4, 'placeholder': 'Kesel haçan we nähili başlandy, näme edildi'},
    )
    anamnesis_vitae = TextAreaField(
        'Ýaşaýyş anamnezi',
        validators=[Optional(), Length(max=8000, message='8000 simwoldan geçmeli däl')],
        render_kw={'rows': 3,
                   'placeholder': 'Geçiren keselleri, operasiýalary, zyýanly endikleri'},
    )
    objective_status = TextAreaField(
        'Obýektiw ýagdaýy',
        validators=[
            DataRequired(message='Obýektiw ýagdaýyny ýazyň'),
            Length(max=8000, message='8000 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 5,
                   'placeholder': 'Umumy ýagdaýy, deri, öýken, ýürek, garyn, peşew çykaryş'},
    )
    local_status = TextAreaField(
        'Lokal status',
        validators=[Optional(), Length(max=8000, message='8000 simwoldan geçmeli däl')],
        render_kw={'rows': 3, 'placeholder': 'Kesellän ýeriň ýagdaýy'},
    )
    diagnosis_rationale = TextAreaField(
        'Diagnozyň esaslandyrylyşy',
        validators=[Optional(), Length(max=8000, message='8000 simwoldan geçmeli däl')],
        render_kw={'rows': 3, 'placeholder': 'Çaklama diagnoz nämä esaslanýar'},
    )
    examination_plan = TextAreaField(
        'Barlag meýilnamasy',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Geçirilmeli analizler we barlaglar'},
    )
    treatment_plan = TextAreaField(
        'Bejergi meýilnamasy',
        validators=[Optional(), Length(max=4000, message='4000 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Режim, derman bejergisi, operasiýa'},
    )

    temperature = DecimalField(
        'Temperaturasy (°C)',
        validators=[Optional(), NumberRange(min=30, max=45, message='30-45 °C aralygynda bolmaly')],
        places=1,
        render_kw={'placeholder': '36.6', 'step': '0.1'},
    )
    pulse = IntegerField(
        'Puls (1 min)',
        validators=[Optional(), NumberRange(min=20, max=300, message='20-300 aralygynda bolmaly')],
        render_kw={'placeholder': '72'},
    )
    systolic = IntegerField(
        'Ýokarky basyş',
        validators=[Optional(), NumberRange(min=40, max=300, message='40-300 aralygynda bolmaly')],
        render_kw={'placeholder': '120'},
    )
    diastolic = IntegerField(
        'Aşaky basyş',
        validators=[Optional(), NumberRange(min=20, max=200, message='20-200 aralygynda bolmaly')],
        render_kw={'placeholder': '80'},
    )
    height = IntegerField(
        'Boýy (sm)',
        validators=[Optional(), NumberRange(min=30, max=250, message='30-250 sm aralygynda bolmaly')],
        render_kw={'placeholder': '170'},
    )
    weight = DecimalField(
        'Agramy (kg)',
        validators=[Optional(), NumberRange(min=1, max=500, message='1-500 kg aralygynda bolmaly')],
        places=1,
        render_kw={'placeholder': '70', 'step': '0.1'},
    )

    submit = SubmitField('Ýatda saklamak')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        # a pressure is a pair — one half of it is not a reading
        if (self.systolic.data is None) != (self.diastolic.data is None):
            self.systolic.errors.append('Basyşyň iki sanyny hem giriziň.')
            return False
        if (self.systolic.data is not None and self.diastolic.data is not None
                and self.diastolic.data >= self.systolic.data):
            self.diastolic.errors.append('Aşaky basyş ýokarkydan kiçi bolmaly.')
            return False
        return True


class AllergyForm(FlaskForm):
    """Adding one allergy to a patient's record."""

    substance = StringField(
        'Serişde',
        validators=[
            DataRequired(message='Serişdäniň adyny giriziň'),
            Length(max=200, message='200 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: Penisillin'},
    )
    severity = SelectField(
        'Agyrlygy',
        validators=[DataRequired(message='Agyrlygyny saýlaň')],
    )
    reaction = StringField(
        'Reaksiýasy',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Mysal: bedende örgün, dem gysma'},
    )
    note = StringField(
        'Bellik',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'placeholder': 'Bellik (islege görä)'},
    )
    submit = SubmitField('Goşmak')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.severity.choices = list(PatientAllergy.SEVERITIES.items())
        self.severity.data = self.severity.data or PatientAllergy.SEVERITY_MODERATE


class AllergyRemoveForm(FlaskForm):
    """Withdrawing an allergy entered by mistake. A reason is required — an
    allergy that quietly vanishes is worse than one that was never written."""

    reason = StringField(
        'Aýyrmagyň sebäbi',
        validators=[
            DataRequired(message='Sebäbini ýazyň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: ýalňyş girizilen, tassyklanmady'},
    )
    submit = SubmitField('Aýyrmak')


class OrderResultForm(FlaskForm):
    """Writing down what an ordered analysis or study came back with.

    The result is text rather than a set of numbered fields on purpose: the
    catalogue holds hundreds of analyses with different reference ranges, and a
    doctor reading a case history reads sentences. The nurse who carried the
    tube is not the author here — whoever writes the result signs it.
    """

    result = TextAreaField(
        'Netije',
        validators=[
            DataRequired(message='Netijesini ýazyň'),
            Length(max=8000, message='8000 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 6, 'placeholder': 'Barlagyň netijesi'},
    )
    completed_at = DateTimeLocalField(
        'Ýerine ýetirilen wagty',
        validators=[Optional()],
        format='%Y-%m-%dT%H:%M',
    )
    submit = SubmitField('Ýatda saklamak')

    def validate_completed_at(self, field):
        if field.data and field.data > datetime.now():
            raise ValidationError('Geljekki wagt görkezilip bilinmeýär.')


class OrderCancelForm(FlaskForm):
    """Calling off an order that was never carried out. A reason is required —
    an order that silently disappears is indistinguishable from one nobody
    got round to."""

    reason = StringField(
        'Ýatyrmagyň sebäbi',
        validators=[
            DataRequired(message='Sebäbini ýazyň'),
            Length(max=500, message='500 simwoldan geçmeli däl'),
        ],
        render_kw={'placeholder': 'Mysal: ýalňyş bellenen, gerek däl'},
    )
    submit = SubmitField('Ýatyrmak')


class ConsultationForm(FlaskForm):
    """Calling in a specialist. The service comes from the shared ugur
    catalogue, the doctor from those who have that ugur assigned to them."""

    direction_id = SelectField(
        'Ugur',
        coerce=int,
        validators=[DataRequired(message='Ugry saýlaň')],
    )
    doctor_id = SelectField(
        'Lukman',
        coerce=int,
        validators=[DataRequired(message='Lukmany saýlaň')],
    )
    reason = TextAreaField(
        'Konsultasiýanyň sebäbi',
        validators=[Optional(), Length(max=500, message='500 simwoldan geçmeli däl')],
        render_kw={'rows': 2, 'placeholder': 'Näme üçin çagyrylýar'},
    )
    submit = SubmitField('Bellemek')

    def __init__(self, *args, directions=None, doctors=None, allowed=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.direction_id.choices = [(d.id, f'{d.name} — {d.price_display} manat')
                                     for d in (directions or [])]
        self.doctor_id.choices = [(d.id, d.full_name) for d in (doctors or [])]
        # {direction_id: {doctor_id}} — which doctor may take which ugur is
        # decided in the admin section; the form only accepts pairs from there,
        # and the same map narrows the dropdown in the browser.
        self._allowed = allowed or {}

    def validate_doctor_id(self, field):
        if self.direction_id.data and field.data not in self._allowed.get(self.direction_id.data, set()):
            raise ValidationError('Bu ugur boýunça saýlanan lukman bellenmedik.')


class ConsultationConclusionForm(FlaskForm):
    """The specialist's finding, entered by the attending doctor or the head."""

    conclusion = TextAreaField(
        'Konsultantyň netijesi',
        validators=[
            DataRequired(message='Netijesini ýazyň'),
            Length(max=8000, message='8000 simwoldan geçmeli däl'),
        ],
        render_kw={'rows': 6, 'placeholder': 'Konsultantyň gözden geçirmesi we maslahaty'},
    )
    performed_at = DateTimeLocalField(
        'Konsultasiýanyň wagty',
        validators=[Optional()],
        format='%Y-%m-%dT%H:%M',
    )
    submit = SubmitField('Ýatda saklamak')

    def validate_performed_at(self, field):
        if field.data and field.data > datetime.now():
            raise ValidationError('Geljekki wagt görkezilip bilinmeýär.')
