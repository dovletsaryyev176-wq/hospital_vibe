from datetime import datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, logout_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, subqueryload
from app.inpatient import inpatient_bp
from app.inpatient.forms import (HospitalizationForm, BedAssignmentForm,
                                 DoctorAssignmentForm, DiaryEntryForm,
                                 StockReceiptForm, StockAdjustForm, MedicationOrderForm,
                                 DiagnosisForm, DischargeForm, VitalRecordForm,
                                 OperationForm, OperationCancelForm,
                                 AdmissionExamForm, AllergyForm, AllergyRemoveForm,
                                 OrderResultForm, OrderCancelForm,
                                 ConsultationForm, ConsultationConclusionForm,
                                 valid_phone)
from app.extensions import db
from app.models import (Room, Bed, Meal, Patient, User, Hospitalization, HospitalizationRelative,
                        HospitalizationBedStay, HospitalizationDoctorAssignment,
                        HospitalizationDiaryEntry, HospitalizationMealAssignment,
                        Medicine, DepartmentMedicineStock, MedicineStockMovement,
                        HospitalizationMedicationOrder, HospitalizationMedicationDispense,
                        HospitalizationDiagnosis, HospitalizationVitalRecord,
                        Operation, HospitalizationOperation,
                        HospitalizationAdmissionExam, PatientAllergy,
                        Analysis, CombinedAnalysis, AnalysisTool, Blank, DoctorDirection,
                        HospitalizationAnalysisOrder, HospitalizationToolOrder,
                        HospitalizationBlankOrder, HospitalizationConsultation,
                        format_quantity, user_departments, meal_departments)


def inpatient_required(*roles):
    """Decorator factory for inpatient-section routes.
    If roles is empty — allows any role that may enter the inpatient section.
    If roles are specified — user must have one of them (and still be allowed in).
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.is_administrator():
                return redirect(url_for('admin.dashboard'))
            if not current_user.is_active:
                logout_user()
                flash('Siziň ulanyjyňyz bloklanan.', 'danger')
                return redirect(url_for('auth.login'))
            if not current_user.can_access_inpatient():
                flash('Siz ýatymlaýyn bölüme girip bilmeýärsiňiz.', 'danger')
                return redirect(url_for('main.dashboard'))
            if roles and current_user.role not in roles:
                flash('Siz bu bölege girip bilmeýärsiňiz.', 'danger')
                return redirect(url_for('inpatient.dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


inpatient_main_required = inpatient_required()


def user_department_ids():
    """Ids of the departments the current user is attached to.
    Every inpatient query must be scoped by this — a user only ever sees
    their own departments.
    """
    return [d.id for d in current_user.active_departments]


def is_department_head() -> bool:
    return current_user.role == 'department_head'


def active_hospitalization(patient_id):
    return (
        Hospitalization.query
        .filter_by(patient_id=patient_id, status=Hospitalization.STATUS_ACTIVE)
        .first()
    )


def occupied_bed_ids(exclude_hospitalization_id=None):
    """Beds taken by a patient who is currently lying in. A discharged stay keeps
    its bed on record but no longer occupies it."""
    query = db.session.query(Hospitalization.bed_id).filter(
        Hospitalization.status == Hospitalization.STATUS_ACTIVE,
        Hospitalization.bed_id.isnot(None),
    )
    if exclude_hospitalization_id is not None:
        query = query.filter(Hospitalization.id != exclude_hospitalization_id)
    return {row[0] for row in query.all()}


def free_beds_for(department_id, exclude_hospitalization_id=None):
    """(bed, room) pairs of a department that nobody is lying in."""
    taken = occupied_bed_ids(exclude_hospitalization_id)
    rows = (
        db.session.query(Bed, Room)
        .join(Room, Bed.room_id == Room.id)
        .filter(Room.department_id == department_id,
                Room.is_active == True, Bed.is_active == True)  # noqa: E712
        .order_by(Room.name, Bed.name)
        .all()
    )
    return [(bed, room) for bed, room in rows if bed.id not in taken]


def department_doctors(department_id):
    """Active doctors attached to a department — the only ones who may be made
    the attending doctor there."""
    return (
        User.query
        .join(user_departments, user_departments.c.user_id == User.id)
        .filter(user_departments.c.department_id == department_id,
                User.role == 'doctor',
                User.is_active == True)  # noqa: E712
        .order_by(User.full_name)
        .all()
    )


def department_medics(department_id):
    """Everyone in a department who may stand at the table — doctors and the
    head. Wider than department_doctors on purpose: a head operates too."""
    return (
        User.query
        .join(user_departments, user_departments.c.user_id == User.id)
        .filter(user_departments.c.department_id == department_id,
                User.role.in_(('doctor', 'department_head')),
                User.is_active == True)  # noqa: E712
        .order_by(User.full_name)
        .all()
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

@inpatient_bp.route('/')
@inpatient_bp.route('/dashboard')
@inpatient_main_required
def dashboard():
    """The ward at a glance: how full it is, who moved today, and what is left
    hanging — a patient without a bed or without an attending doctor."""
    departments = current_user.active_departments
    dep_ids = [d.id for d in departments]

    room_counts = {}
    bed_counts = {}
    lying_counts = {}
    admitted_today = {}
    discharged_today = {}

    if dep_ids:
        def _grouped(query):
            return dict(query.all())

        room_counts = _grouped(
            db.session.query(Room.department_id, db.func.count(Room.id))
            .filter(Room.department_id.in_(dep_ids), Room.is_active == True)  # noqa: E712
            .group_by(Room.department_id)
        )
        bed_counts = _grouped(
            db.session.query(Room.department_id, db.func.count(Bed.id))
            .join(Bed, Bed.room_id == Room.id)
            .filter(Room.department_id.in_(dep_ids),
                    Room.is_active == True, Bed.is_active == True)  # noqa: E712
            .group_by(Room.department_id)
        )
        lying_counts = _grouped(
            db.session.query(Hospitalization.department_id, db.func.count(Hospitalization.id))
            .filter(Hospitalization.department_id.in_(dep_ids),
                    Hospitalization.status == Hospitalization.STATUS_ACTIVE)
            .group_by(Hospitalization.department_id)
        )

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        admitted_today = _grouped(
            db.session.query(Hospitalization.department_id, db.func.count(Hospitalization.id))
            .filter(Hospitalization.department_id.in_(dep_ids),
                    Hospitalization.admitted_at >= today)
            .group_by(Hospitalization.department_id)
        )
        discharged_today = _grouped(
            db.session.query(Hospitalization.department_id, db.func.count(Hospitalization.id))
            .filter(Hospitalization.department_id.in_(dep_ids),
                    Hospitalization.discharged_at >= today)
            .group_by(Hospitalization.department_id)
        )

    # Whatever still needs a hand. Scoped to the viewer's departments like
    # everything else in the section.
    needs_attention = []
    if dep_ids:
        # stays past the grace period with no admission examination written
        exam_written = db.session.query(HospitalizationAdmissionExam.hospitalization_id)
        exam_due_by = datetime.now() - HospitalizationAdmissionExam.DUE_WITHIN

        needs_attention = (
            Hospitalization.query
            .options(joinedload(Hospitalization.patient),
                     joinedload(Hospitalization.department),
                     joinedload(Hospitalization.admission_exam))
            .filter(Hospitalization.department_id.in_(dep_ids),
                    Hospitalization.status == Hospitalization.STATUS_ACTIVE,
                    db.or_(Hospitalization.bed_id.is_(None),
                           Hospitalization.doctor_id.is_(None),
                           db.and_(Hospitalization.admitted_at < exam_due_by,
                                   ~Hospitalization.id.in_(exam_written))))
            .order_by(Hospitalization.admitted_at)
            .limit(20)
            .all()
        )

    totals = {
        'beds': sum(bed_counts.values()),
        'lying': sum(lying_counts.values()),
        'admitted_today': sum(admitted_today.values()),
        'discharged_today': sum(discharged_today.values()),
    }
    totals['free'] = max(0, totals['beds'] - totals['lying'])
    totals['occupancy'] = round(totals['lying'] * 100 / totals['beds']) if totals['beds'] else 0

    return render_template(
        'inpatient/dashboard.html',
        departments=departments,
        room_counts=room_counts,
        bed_counts=bed_counts,
        lying_counts=lying_counts,
        admitted_today=admitted_today,
        discharged_today=discharged_today,
        needs_attention=needs_attention,
        totals=totals,
    )


# ── Patients ──────────────────────────────────────────────────────────────────

PATIENTS_PER_PAGE = 15


@inpatient_bp.route('/syrkawlar')
@inpatient_main_required
def patients_list():
    search = request.args.get('q', '').strip()
    place_filter = request.args.get('place', '').strip()
    mine_only = request.args.get('mine', '') == '1'
    page = request.args.get('page', 1, type=int)

    dep_ids = user_department_ids()
    head = is_department_head()
    is_doctor = current_user.role == 'doctor'

    lying_patient_ids = db.session.query(Hospitalization.patient_id).filter(
        Hospitalization.status == Hospitalization.STATUS_ACTIVE)

    query = Patient.query

    if search:
        like = f'%{search}%'
        by_history = db.session.query(Hospitalization.patient_id).filter(
            Hospitalization.history_number.ilike(like))
        query = query.filter(db.or_(
            Patient.full_name.ilike(like),
            Patient.passport_number.ilike(like),
            Patient.insurance_number.ilike(like),
            Patient.citizenship.ilike(like),
            Patient.id.in_(by_history),
        ))

    if head:
        # the head sees every patient — that is how they pick who to admit
        if place_filter == 'in':
            query = query.filter(Patient.id.in_(lying_patient_ids))
        elif place_filter == 'out':
            query = query.filter(~Patient.id.in_(lying_patient_ids))
    else:
        # everyone else only sees who is lying in their own departments
        if not dep_ids:
            query = query.filter(db.false())
        else:
            scoped = lying_patient_ids.filter(Hospitalization.department_id.in_(dep_ids))
            if is_doctor and mine_only:
                scoped = scoped.filter(Hospitalization.doctor_id == current_user.id)
            query = query.filter(Patient.id.in_(scoped))

    pagination = query.order_by(Patient.full_name).paginate(
        page=page, per_page=PATIENTS_PER_PAGE, error_out=False)

    hospitalizations = {}
    patient_ids = [p.id for p in pagination.items]
    if patient_ids:
        rows = (
            Hospitalization.query
            .options(joinedload(Hospitalization.department),
                     joinedload(Hospitalization.room),
                     joinedload(Hospitalization.bed),
                     joinedload(Hospitalization.doctor))
            .filter(Hospitalization.patient_id.in_(patient_ids),
                    Hospitalization.status == Hospitalization.STATUS_ACTIVE)
            .all()
        )
        hospitalizations = {h.patient_id: h for h in rows}

    return render_template(
        'inpatient/patients/list.html',
        patients=pagination.items,
        pagination=pagination,
        hospitalizations=hospitalizations,
        my_dep_ids=set(dep_ids),
        is_head=head,
        is_doctor=is_doctor,
        search=search,
        place_filter=place_filter,
        mine_only=mine_only,
    )


@inpatient_bp.route('/syrkawlar/<int:patient_id>')
@inpatient_main_required
def patients_detail(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    dep_ids = set(user_department_ids())
    current = active_hospitalization(patient_id)

    # A non-head may only open the card of someone lying in their own department
    if not is_department_head():
        if current is None or current.department_id not in dep_ids:
            flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
            return redirect(url_for('inpatient.patients_list'))

    # Past stays are only shown for the viewer's own departments
    stay_details = (
        subqueryload(Hospitalization.bed_stays).joinedload(HospitalizationBedStay.room),
        subqueryload(Hospitalization.bed_stays).joinedload(HospitalizationBedStay.bed),
        subqueryload(Hospitalization.bed_stays).joinedload(HospitalizationBedStay.assigned_by),
        subqueryload(Hospitalization.doctor_assignments)
        .joinedload(HospitalizationDoctorAssignment.doctor),
        subqueryload(Hospitalization.doctor_assignments)
        .joinedload(HospitalizationDoctorAssignment.assigned_by),
        # past stays print their closing diagnosis in the list
        subqueryload(Hospitalization.diagnoses),
    )
    past = (
        Hospitalization.query
        .options(joinedload(Hospitalization.department),
                 joinedload(Hospitalization.room),
                 joinedload(Hospitalization.bed),
                 *stay_details)
        .filter(Hospitalization.patient_id == patient_id,
                Hospitalization.status == Hospitalization.STATUS_DISCHARGED,
                Hospitalization.department_id.in_(dep_ids) if dep_ids else db.false())
        .order_by(Hospitalization.admitted_at.desc())
        .all()
    )

    return render_template(
        'inpatient/patients/detail.html',
        patient=patient,
        current=current,
        past=past,
        my_dep_ids=dep_ids,
        is_head=is_department_head(),
    )


# ── Admit (department head) ───────────────────────────────────────────────────

def _parse_relatives(form):
    """Relative rows arrive as parallel arrays; returns (rows, errors)."""
    names = form.getlist('relative_full_name')
    phones = form.getlist('relative_phone')
    relations = form.getlist('relative_relation')

    rows, errors = [], []
    for index in range(max(len(names), len(phones), len(relations))):
        name = (names[index] if index < len(names) else '').strip()
        phone = (phones[index] if index < len(phones) else '').strip()
        relation = (relations[index] if index < len(relations) else '').strip()
        if not name and not phone and not relation:
            continue
        if not name or not phone:
            errors.append(f'{index + 1}-nji setirde hossaryň FAA-syny we telefonyny giriziň.')
        elif not valid_phone(phone):
            errors.append(f'{index + 1}-nji setirde dogry telefon belgisini giriziň.')
        else:
            rows.append({'full_name': name, 'phone_number': phone, 'relation': relation or None})

    if not rows and not errors:
        errors.append('Iň azyndan bir hossaryň telefon belgisini giriziň.')
    return rows, errors


@inpatient_bp.route('/syrkawlar/<int:patient_id>/yatyrmak', methods=['GET', 'POST'])
@inpatient_required('department_head')
def patients_admit(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    if not patient.is_active:
        flash('Bloklanan syrkawy ýatyryp bolmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    existing = active_hospitalization(patient_id)
    if existing is not None:
        flash(f'«{patient.full_name}» eýýäm ýatyr.', 'warning')
        return redirect(url_for('inpatient.patients_list'))

    departments = current_user.active_departments
    if not departments:
        flash('Size bölüm bellenmedik. Dolandyryja ýüz tutuň.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    form = HospitalizationForm(departments=departments)
    relatives, relative_errors = [], []

    if form.validate_on_submit():
        relatives, relative_errors = _parse_relatives(request.form)

        if form.department_id.data not in {d.id for d in departments}:
            relative_errors.append('Diňe öz bölümiňize ýatyryp bilersiňiz.')

        if not relative_errors:
            hospitalization = Hospitalization(
                patient_id=patient.id,
                department_id=form.department_id.data,
                history_number=form.history_number.data.strip(),
                status=Hospitalization.STATUS_ACTIVE,
                admitted_by_id=current_user.id,
            )
            for row in relatives:
                hospitalization.relatives.append(HospitalizationRelative(**row))
            # a stay is opened because of something — the reason goes on record
            # in the same transaction, never as an afterthought
            hospitalization.diagnoses.append(HospitalizationDiagnosis(
                kind=HospitalizationDiagnosis.KIND_PRELIMINARY,
                text=form.diagnosis.data.strip(),
                code=(form.diagnosis_code.data or '').strip() or None,
                author_id=current_user.id,
            ))
            db.session.add(hospitalization)
            try:
                db.session.commit()
            except IntegrityError:
                # Two heads submitting the same history number at once: the form
                # check passes for both, the unique index rejects the second.
                db.session.rollback()
                relative_errors.append('Bu belgili kesel taryhy eýýäm bar.')
            else:
                flash(f'«{patient.full_name}» ýatymlaýyn bölüme ýatyryldy.', 'success')
                return redirect(url_for('inpatient.patients_detail', patient_id=patient.id))
    elif request.method == 'POST':
        relatives, relative_errors = _parse_relatives(request.form)

    return render_template(
        'inpatient/patients/admit.html',
        form=form,
        patient=patient,
        relatives=relatives,
        relative_errors=relative_errors,
    )


@inpatient_bp.route('/syrkawlar/<int:patient_id>/cykarmak', methods=['GET', 'POST'])
@inpatient_required('department_head')
def patients_discharge(patient_id):
    """Closing a stay: the final diagnosis, the outcome and the epicrisis are
    written in the same act that ends it — a discharge is a document, not a
    status flip."""
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    current = active_hospitalization(patient_id)
    if current is None:
        flash(f'«{patient.full_name}» ýatmaýar.', 'warning')
        return redirect(url_for('inpatient.patients_list'))

    if current.department_id not in set(user_department_ids()):
        flash('Diňe öz bölümiňiziň syrkawyny çykaryp bilersiňiz.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    form = DischargeForm()

    if request.method == 'GET':
        # start from what is already known, so the head corrects instead of retypes
        known = current.final_diagnosis or current.clinical_diagnosis or current.preliminary_diagnosis
        if known is not None:
            form.diagnosis.data = known.text
            form.diagnosis_code.data = known.code

    if form.validate_on_submit():
        discharged_at = datetime.now()

        current.status = Hospitalization.STATUS_DISCHARGED
        current.discharged_at = discharged_at
        current.discharged_by_id = current_user.id
        current.outcome = form.outcome.data
        current.epicrisis = form.epicrisis.data.strip()
        current.recommendations = (form.recommendations.data or '').strip() or None

        current.diagnoses.append(HospitalizationDiagnosis(
            kind=HospitalizationDiagnosis.KIND_FINAL,
            text=form.diagnosis.data.strip(),
            code=(form.diagnosis_code.data or '').strip() or None,
            author_id=current_user.id,
        ))

        open_stay = current.current_bed_stay
        if open_stay is not None:
            open_stay.ended_at = discharged_at

        open_doctor = current.current_doctor_assignment
        if open_doctor is not None:
            open_doctor.ended_at = discharged_at

        for meal_assignment in current.active_meal_assignments:
            meal_assignment.ended_at = discharged_at
            meal_assignment.ended_by_id = current_user.id

        for order in current.active_medication_orders:
            order.status = HospitalizationMedicationOrder.STATUS_FINISHED
            order.stopped_at = discharged_at
            order.stopped_by_id = current_user.id

        # a still-planned operation cannot happen to a discharged patient
        for operation in current.planned_operations:
            operation.status = HospitalizationOperation.STATUS_CANCELLED
            operation.cancelled_at = discharged_at
            operation.cancelled_by_id = current_user.id
            operation.cancel_reason = 'Syrkaw çykaryldy'

        db.session.commit()

        flash(f'«{patient.full_name}» ýatymlaýyn bölümden çykaryldy.', 'success')
        return redirect(url_for('inpatient.patients_detail', patient_id=patient.id))

    return render_template(
        'inpatient/patients/discharge.html',
        form=form,
        patient=patient,
        current=current,
    )


# ── Bed assignment (senior nurse) ─────────────────────────────────────────────

@inpatient_bp.route('/syrkawlar/<int:patient_id>/krowat', methods=['GET', 'POST'])
@inpatient_required('senior_nurse')
def patients_assign_bed(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    current = active_hospitalization(patient_id)
    if current is None:
        flash(f'«{patient.full_name}» ýatmaýar.', 'warning')
        return redirect(url_for('inpatient.patients_list'))

    if current.department_id not in set(user_department_ids()):
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    beds = free_beds_for(current.department_id, exclude_hospitalization_id=current.id)
    form = BedAssignmentForm(beds=beds)

    if request.method == 'GET' and current.bed_id:
        form.bed_id.data = current.bed_id

    if form.validate_on_submit():
        chosen = next((b for b, _ in beds if b.id == form.bed_id.data), None)
        if chosen is None:
            flash('Bu krowat elýeterli däl. Sanawy täzeläň.', 'danger')
            return redirect(url_for('inpatient.patients_assign_bed', patient_id=patient.id))

        if current.bed_id == chosen.id:
            flash('Syrkaw eýýäm şol krowatda ýatyr.', 'info')
            return redirect(url_for('inpatient.patients_detail', patient_id=patient.id))

        # Re-check occupancy with a row lock right before writing: two nurses
        # may pass the free-beds check at the same moment (no-op on SQLite).
        conflict = (
            Hospitalization.query
            .filter(Hospitalization.bed_id == chosen.id,
                    Hospitalization.status == Hospitalization.STATUS_ACTIVE,
                    Hospitalization.id != current.id)
            .with_for_update()
            .first()
        )
        if conflict is not None:
            db.session.rollback()
            flash('Bu krowat eýýäm başga syrkawa bellenildi. Sanawy täzeläň.', 'danger')
            return redirect(url_for('inpatient.patients_assign_bed', patient_id=patient.id))

        moved_at = datetime.now()

        # close the period on the previous bed, then open a new one — every bed
        # the patient lay in stays on record with the price of that moment
        open_stay = current.current_bed_stay
        if open_stay is not None:
            open_stay.ended_at = moved_at

        current.bed_stays.append(HospitalizationBedStay(
            room_id=chosen.room_id,
            bed_id=chosen.id,
            price=chosen.price,
            is_insurance=chosen.is_insurance,
            started_at=moved_at,
            assigned_by_id=current_user.id,
        ))

        current.bed_id = chosen.id
        current.room_id = chosen.room_id
        current.bed_assigned_at = moved_at
        current.bed_assigned_by_id = current_user.id
        db.session.commit()

        flash(f'«{patient.full_name}» üçin palata we krowat bellenildi.', 'success')
        return redirect(url_for('inpatient.patients_detail', patient_id=patient.id))

    return render_template(
        'inpatient/patients/assign_bed.html',
        form=form,
        patient=patient,
        current=current,
        beds=beds,
    )


# ── Attending doctor (department head) ────────────────────────────────────────

@inpatient_bp.route('/syrkawlar/<int:patient_id>/lukman', methods=['GET', 'POST'])
@inpatient_required('department_head')
def patients_assign_doctor(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    current = active_hospitalization(patient_id)
    if current is None:
        flash(f'«{patient.full_name}» ýatmaýar.', 'warning')
        return redirect(url_for('inpatient.patients_list'))

    if current.department_id not in set(user_department_ids()):
        flash('Diňe öz bölümiňiziň syrkawyna lukman belläp bilersiňiz.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    doctors = department_doctors(current.department_id)
    form = DoctorAssignmentForm(doctors=doctors)

    if request.method == 'GET' and current.doctor_id:
        form.doctor_id.data = current.doctor_id

    if form.validate_on_submit():
        chosen = next((d for d in doctors if d.id == form.doctor_id.data), None)
        if chosen is None:
            flash('Bu lukman bu bölüme degişli däl.', 'danger')
            return redirect(url_for('inpatient.patients_assign_doctor', patient_id=patient.id))

        if current.doctor_id == chosen.id:
            flash('Bu lukman eýýäm bellenildi.', 'info')
            return redirect(url_for('inpatient.patients_detail', patient_id=patient.id))

        changed_at = datetime.now()

        # close the previous doctor's period, then open the new one — it stays
        # visible who was responsible for the patient on which days
        open_assignment = current.current_doctor_assignment
        if open_assignment is not None:
            open_assignment.ended_at = changed_at

        current.doctor_assignments.append(HospitalizationDoctorAssignment(
            doctor_id=chosen.id,
            started_at=changed_at,
            assigned_by_id=current_user.id,
        ))

        current.doctor_id = chosen.id
        current.doctor_assigned_at = changed_at
        current.doctor_assigned_by_id = current_user.id
        db.session.commit()

        flash(f'«{patient.full_name}» üçin bejeriji lukman: {chosen.full_name}.', 'success')
        return redirect(url_for('inpatient.patients_detail', patient_id=patient.id))

    return render_template(
        'inpatient/patients/assign_doctor.html',
        form=form,
        patient=patient,
        current=current,
        doctors=doctors,
    )


# ── Diary (gündelik) ──────────────────────────────────────────────────────────

DIARY_WRITER_ROLES = ('doctor', 'department_head')


def can_write_diary(hospitalization) -> bool:
    """Doctors and the head of that department write the diary; nurses read it."""
    return (current_user.role in DIARY_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids()))


def _load_visible_hospitalization(hospitalization_id):
    """Fetch a hospitalization the current user is allowed to look into, or None."""
    hospitalization = (
        Hospitalization.query
        .options(joinedload(Hospitalization.patient),
                 joinedload(Hospitalization.department),
                 joinedload(Hospitalization.doctor))
        .filter_by(id=hospitalization_id)
        .first()
    )
    if hospitalization is None:
        abort(404)
    if hospitalization.department_id not in set(user_department_ids()):
        return None
    return hospitalization


@inpatient_bp.route('/gundelik/<int:hospitalization_id>', methods=['GET', 'POST'])
@inpatient_main_required
def diary(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    may_write = can_write_diary(hospitalization) and hospitalization.is_open
    form = DiaryEntryForm() if may_write else None

    if may_write and form.validate_on_submit():
        entry = HospitalizationDiaryEntry(
            hospitalization_id=hospitalization.id,
            author_id=current_user.id,
            complaints=(form.complaints.data or '').strip() or None,
            objective=(form.objective.data or '').strip() or None,
            dynamics=(form.dynamics.data or '').strip() or None,
            plan=(form.plan.data or '').strip() or None,
            temperature=form.temperature.data,
            blood_pressure=(form.blood_pressure.data or '').strip() or None,
            pulse=form.pulse.data,
        )
        db.session.add(entry)
        db.session.commit()
        flash('Gündelik ýazgysy goşuldy.', 'success')
        return redirect(url_for('inpatient.diary', hospitalization_id=hospitalization.id))

    if request.method == 'POST' and not may_write:
        flash('Siz gündelige ýazgy goşup bilmeýärsiňiz.', 'danger')
        return redirect(url_for('inpatient.diary', hospitalization_id=hospitalization.id))

    entries = (
        HospitalizationDiaryEntry.query
        .options(joinedload(HospitalizationDiaryEntry.author))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationDiaryEntry.created_at.desc())
        .all()
    )

    return render_template(
        'inpatient/diary/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        entries=entries,
        form=form,
        may_write=may_write,
    )


@inpatient_bp.route('/gundelik/yazgy/<int:entry_id>', methods=['GET', 'POST'])
@inpatient_main_required
def diary_edit(entry_id):
    entry = db.session.get(HospitalizationDiaryEntry, entry_id)
    if entry is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(entry.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    if not entry.is_editable_by(current_user):
        flash('Ýazgyny diňe awtory ýazylandan soň 24 sagadyň dowamynda üýtgedip bilýär.', 'danger')
        return redirect(url_for('inpatient.diary', hospitalization_id=hospitalization.id))

    form = DiaryEntryForm(obj=entry)

    if form.validate_on_submit():
        entry.complaints = (form.complaints.data or '').strip() or None
        entry.objective = (form.objective.data or '').strip() or None
        entry.dynamics = (form.dynamics.data or '').strip() or None
        entry.plan = (form.plan.data or '').strip() or None
        entry.temperature = form.temperature.data
        entry.blood_pressure = (form.blood_pressure.data or '').strip() or None
        entry.pulse = form.pulse.data
        entry.updated_at = datetime.now()
        db.session.commit()
        flash('Gündelik ýazgysy üýtgedildi.', 'success')
        return redirect(url_for('inpatient.diary', hospitalization_id=hospitalization.id))

    return render_template(
        'inpatient/diary/edit.html',
        form=form,
        entry=entry,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
    )


# ── Meals (naharlar) ──────────────────────────────────────────────────────────

def department_meals(department_id):
    """Active meals attached to a department in the admin panel."""
    return (
        Meal.query
        .join(meal_departments, meal_departments.c.meal_id == Meal.id)
        .filter(meal_departments.c.department_id == department_id,
                Meal.is_active == True)  # noqa: E712
        .order_by(Meal.name)
        .all()
    )


def can_assign_meals(hospitalization) -> bool:
    """Only the senior nurse of that department, and only while the patient lies in."""
    return (current_user.role == 'senior_nurse'
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


@inpatient_bp.route('/naharlar/<int:hospitalization_id>')
@inpatient_main_required
def meals(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    assignments = (
        HospitalizationMealAssignment.query
        .options(joinedload(HospitalizationMealAssignment.meal),
                 joinedload(HospitalizationMealAssignment.assigned_by),
                 joinedload(HospitalizationMealAssignment.ended_by))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationMealAssignment.started_at.desc())
        .all()
    )
    active = [a for a in assignments if a.ended_at is None]
    finished = [a for a in assignments if a.ended_at is not None]

    may_assign = can_assign_meals(hospitalization)
    available = []
    if may_assign:
        active_meal_ids = {a.meal_id for a in active}
        available = [m for m in department_meals(hospitalization.department_id)
                     if m.id not in active_meal_ids]

    return render_template(
        'inpatient/meals/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        active=active,
        finished=finished,
        available=available,
        may_assign=may_assign,
    )


@inpatient_bp.route('/naharlar/<int:hospitalization_id>/goshmak', methods=['POST'])
@inpatient_required('senior_nurse')
def meals_add(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.meals', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — nahar bellemek bolmaýar.', 'danger')
        return redirect(back)

    selected_ids = set(request.form.getlist('meal_ids', type=int))
    if not selected_ids:
        flash('Nahar saýlanmady.', 'warning')
        return redirect(back)

    allowed = {m.id: m for m in department_meals(hospitalization.department_id)}
    already_on = {a.meal_id for a in hospitalization.active_meal_assignments}

    added, started_at = 0, datetime.now()
    for meal_id in selected_ids:
        meal = allowed.get(meal_id)
        if meal is None or meal_id in already_on:
            continue
        hospitalization.meal_assignments.append(HospitalizationMealAssignment(
            meal_id=meal.id,
            price=meal.price,
            is_insurance=meal.is_insurance,
            started_at=started_at,
            assigned_by_id=current_user.id,
        ))
        added += 1

    if not added:
        flash('Saýlanan naharlar elýeterli däl ýa-da eýýäm bellenen.', 'danger')
        return redirect(back)

    db.session.commit()
    flash(f'{added} nahar bellenildi.', 'success')
    return redirect(back)


@inpatient_bp.route('/naharlar/bellenme/<int:assignment_id>/besetmek', methods=['POST'])
@inpatient_required('senior_nurse')
def meals_stop(assignment_id):
    assignment = db.session.get(HospitalizationMealAssignment, assignment_id)
    if assignment is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(assignment.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.meals', hospitalization_id=hospitalization.id)

    if not assignment.is_open:
        flash('Bu nahar eýýäm bes edilen.', 'info')
        return redirect(back)

    assignment.ended_at = datetime.now()
    assignment.ended_by_id = current_user.id
    db.session.commit()

    flash(f'«{assignment.meal.name}» bes edildi.', 'success')
    return redirect(back)


# ── Ward drug store (ammar) ───────────────────────────────────────────────────

MOVEMENTS_PER_PAGE = 30

# The senior nurse keeps the store; the head of the department only looks at it
STOCK_VIEW_ROLES = ('senior_nurse', 'department_head')

# Who writes drug orders — the same people who write the diary
MEDICATION_WRITER_ROLES = ('doctor', 'department_head')


def parse_quantity(raw):
    """A positive drug amount with two decimals, or None if the input is not one.

    Amounts arrive from plain inline forms (the dispense button sits in a table
    row), so they are parsed here instead of through WTForms.
    """
    try:
        value = Decimal((raw or '').strip().replace(',', '.'))
    except (InvalidOperation, AttributeError):
        return None
    # is_finite() first — comparing a NaN raises instead of returning False.
    # The upper bound is what Numeric(10, 2) can hold.
    if not value.is_finite() or value <= 0 or value > Decimal('99999999.99'):
        return None
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def active_medicines():
    return Medicine.query.filter_by(is_active=True).order_by(Medicine.name).all()


def selected_department_id(dep_ids):
    """Which department's store is being looked at — ?dep=, else the first one.
    A department the user is not attached to is never accepted."""
    requested = request.args.get('dep', 0, type=int)
    if requested and requested in dep_ids:
        return requested
    return dep_ids[0] if dep_ids else None


def department_stock(department_id, only_positive=False):
    """Stock rows of a department, drug name first."""
    query = (
        DepartmentMedicineStock.query
        .options(joinedload(DepartmentMedicineStock.medicine))
        .join(Medicine, DepartmentMedicineStock.medicine_id == Medicine.id)
        .filter(DepartmentMedicineStock.department_id == department_id)
    )
    if only_positive:
        query = query.filter(DepartmentMedicineStock.quantity > 0)
    return query.order_by(Medicine.name).all()


def stock_quantities(department_id):
    """{medicine_id: remaining quantity} for one department."""
    rows = (
        db.session.query(DepartmentMedicineStock.medicine_id, DepartmentMedicineStock.quantity)
        .filter(DepartmentMedicineStock.department_id == department_id)
        .all()
    )
    return {medicine_id: quantity for medicine_id, quantity in rows}


def stock_quantities_display(department_id, medicines):
    """{medicine id as string: formatted remainder} — for the balance hint the
    drug pickers show. Keyed by string because it is handed to the page as JSON.
    """
    quantities = stock_quantities(department_id)
    return {str(m.id): format_quantity(quantities.get(m.id, 0)) for m in medicines}


def locked_stock(department_id, medicine_id):
    """The stock row for (department, drug), created on first touch and locked
    for update — two nurses must not be able to spend the same remainder twice.
    The lock is real on MySQL; on SQLite it is a no-op, as with bed assignment.
    """
    def fetch():
        return (
            DepartmentMedicineStock.query
            .filter_by(department_id=department_id, medicine_id=medicine_id)
            .with_for_update()
            .first()
        )

    row = fetch()
    if row is not None:
        return row

    try:
        with db.session.begin_nested():
            row = DepartmentMedicineStock(
                department_id=department_id,
                medicine_id=medicine_id,
                quantity=Decimal('0'),
            )
            db.session.add(row)
            db.session.flush()
    except IntegrityError:
        # another nurse booked the very first receipt of this drug at the same
        # moment — the unique index rejected us, so take their row
        row = fetch()
    return row


def apply_movement(stock, kind, delta, note=None, dispense=None):
    """Move a stock balance and journal it in one go. The caller commits.

    delta is signed: a receipt is positive, a dispense or write-off negative.
    Nothing else in the module may touch DepartmentMedicineStock.quantity.
    """
    stock.quantity = (stock.quantity or Decimal('0')) + delta
    stock.updated_at = datetime.now()
    movement = MedicineStockMovement(
        department_id=stock.department_id,
        medicine_id=stock.medicine_id,
        kind=kind,
        quantity=delta,
        balance_after=stock.quantity,
        note=note,
        dispense=dispense,
        created_by_id=current_user.id,
    )
    db.session.add(movement)
    return movement


def _store_department(dep_ids):
    """Resolve the department whose store is being worked on, or flash + None."""
    department_id = selected_department_id(dep_ids)
    if department_id is None:
        flash('Size bölüm bellenmedik. Dolandyryja ýüz tutuň.', 'danger')
    return department_id


@inpatient_bp.route('/ammar')
@inpatient_required(*STOCK_VIEW_ROLES)
def stock():
    dep_ids = user_department_ids()
    department_id = _store_department(dep_ids)
    if department_id is None:
        return redirect(url_for('inpatient.dashboard'))

    rows = department_stock(department_id)
    empty_count = sum(1 for row in rows if row.quantity <= 0)

    return render_template(
        'inpatient/stock/list.html',
        departments=[d for d in current_user.active_departments if d.id in dep_ids],
        department_id=department_id,
        rows=rows,
        empty_count=empty_count,
        may_edit=current_user.role == 'senior_nurse',
    )


@inpatient_bp.route('/ammar/girdeji', methods=['GET', 'POST'])
@inpatient_required('senior_nurse')
def stock_receipt():
    dep_ids = user_department_ids()
    department_id = _store_department(dep_ids)
    if department_id is None:
        return redirect(url_for('inpatient.dashboard'))

    medicines = active_medicines()
    form = StockReceiptForm(medicines=medicines)
    back = url_for('inpatient.stock', dep=department_id)

    if form.validate_on_submit():
        medicine = next((m for m in medicines if m.id == form.medicine_id.data), None)
        if medicine is None:
            flash('Bu derman elýeterli däl. Sanawy täzeläň.', 'danger')
            return redirect(url_for('inpatient.stock_receipt', dep=department_id))

        quantity = form.quantity.data
        stock_row = locked_stock(department_id, medicine.id)
        apply_movement(stock_row, MedicineStockMovement.KIND_IN, quantity,
                       note=(form.note.data or '').strip() or None)
        db.session.commit()

        flash(f'«{medicine.name}» — {format_quantity(quantity)} {medicine.unit_display} '
              f'girdeji ýazyldy. Galyndy: {format_quantity(stock_row.quantity)}.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/stock/receipt.html',
        form=form,
        department_id=department_id,
        medicines=medicines,
        quantities=stock_quantities_display(department_id, medicines),
        units={str(m.id): m.unit_display for m in medicines},
        back=back,
    )


@inpatient_bp.route('/ammar/duzedis', methods=['GET', 'POST'])
@inpatient_required('senior_nurse')
def stock_adjust():
    dep_ids = user_department_ids()
    department_id = _store_department(dep_ids)
    if department_id is None:
        return redirect(url_for('inpatient.dashboard'))

    # only what the ward actually holds may be written off or corrected
    rows = department_stock(department_id)
    medicines = [row.medicine for row in rows]
    form = StockAdjustForm(medicines=medicines)
    back = url_for('inpatient.stock', dep=department_id)

    if form.validate_on_submit():
        medicine = next((m for m in medicines if m.id == form.medicine_id.data), None)
        if medicine is None:
            flash('Bu derman ammarda ýok. Sanawy täzeläň.', 'danger')
            return redirect(url_for('inpatient.stock_adjust', dep=department_id))

        quantity = form.quantity.data
        is_writeoff = form.kind.data == MedicineStockMovement.KIND_WRITEOFF
        stock_row = locked_stock(department_id, medicine.id)

        if is_writeoff and stock_row.quantity < quantity:
            # read what we need before the rollback — it expires the objects,
            # and a stock row created just above would not survive it at all
            remaining, unit = format_quantity(stock_row.quantity), medicine.unit_display
            db.session.rollback()
            flash(f'Ammarda ýeterlik derman ýok. Galyndy: {remaining} {unit}.', 'danger')
            return redirect(url_for('inpatient.stock_adjust', dep=department_id))

        delta = -quantity if is_writeoff else quantity
        apply_movement(stock_row, form.kind.data, delta, note=form.note.data.strip())
        db.session.commit()

        flash(f'«{medicine.name}» — galyndy: '
              f'{format_quantity(stock_row.quantity)} {medicine.unit_display}.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/stock/adjust.html',
        form=form,
        department_id=department_id,
        medicines=medicines,
        quantities=stock_quantities_display(department_id, medicines),
        units={str(m.id): m.unit_display for m in medicines},
        back=back,
    )


@inpatient_bp.route('/ammar/hereketler')
@inpatient_required(*STOCK_VIEW_ROLES)
def stock_movements():
    dep_ids = user_department_ids()
    department_id = _store_department(dep_ids)
    if department_id is None:
        return redirect(url_for('inpatient.dashboard'))

    medicine_filter = request.args.get('medicine', 0, type=int)
    kind_filter = request.args.get('kind', '').strip()
    page = request.args.get('page', 1, type=int)

    query = (
        MedicineStockMovement.query
        .options(joinedload(MedicineStockMovement.medicine),
                 joinedload(MedicineStockMovement.created_by))
        .filter(MedicineStockMovement.department_id == department_id)
    )
    if medicine_filter:
        query = query.filter(MedicineStockMovement.medicine_id == medicine_filter)
    if kind_filter in MedicineStockMovement.KINDS:
        query = query.filter(MedicineStockMovement.kind == kind_filter)

    pagination = query.order_by(MedicineStockMovement.created_at.desc(),
                                MedicineStockMovement.id.desc()).paginate(
        page=page, per_page=MOVEMENTS_PER_PAGE, error_out=False)

    return render_template(
        'inpatient/stock/movements.html',
        departments=[d for d in current_user.active_departments if d.id in dep_ids],
        department_id=department_id,
        movements=pagination.items,
        pagination=pagination,
        medicines=[row.medicine for row in department_stock(department_id)],
        medicine_filter=medicine_filter,
        kind_filter=kind_filter,
        kinds=MedicineStockMovement.KINDS,
    )


# ── Medication orders and dispensing (dermanlar) ──────────────────────────────

def can_order_medication(hospitalization) -> bool:
    """Doctors and the head of that department prescribe; nurses dispense."""
    return (current_user.role in MEDICATION_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


def can_dispense(hospitalization) -> bool:
    """Only the senior nurse of that department, and only while the patient lies in."""
    return (current_user.role == 'senior_nurse'
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


@inpatient_bp.route('/dermanlar/<int:hospitalization_id>')
@inpatient_main_required
def medications(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    orders = (
        HospitalizationMedicationOrder.query
        .options(joinedload(HospitalizationMedicationOrder.medicine),
                 joinedload(HospitalizationMedicationOrder.doctor),
                 joinedload(HospitalizationMedicationOrder.stopped_by),
                 subqueryload(HospitalizationMedicationOrder.dispenses)
                 .joinedload(HospitalizationMedicationDispense.given_by))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationMedicationOrder.started_at.desc())
        .all()
    )
    active = [o for o in orders if o.is_active]
    finished = [o for o in orders if not o.is_active]

    dispenses = (
        HospitalizationMedicationDispense.query
        .options(joinedload(HospitalizationMedicationDispense.medicine),
                 joinedload(HospitalizationMedicationDispense.given_by),
                 joinedload(HospitalizationMedicationDispense.cancelled_by))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationMedicationDispense.given_at.desc())
        .all()
    )

    return render_template(
        'inpatient/medications/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        active=active,
        finished=finished,
        dispenses=dispenses,
        quantities=stock_quantities(hospitalization.department_id),
        may_order=can_order_medication(hospitalization),
        may_dispense=can_dispense(hospitalization),
    )


@inpatient_bp.route('/dermanlar/<int:hospitalization_id>/bellemek', methods=['GET', 'POST'])
@inpatient_required(*MEDICATION_WRITER_ROLES)
def medications_add(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.medications', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — derman bellemek bolmaýar.', 'danger')
        return redirect(back)

    medicines = active_medicines()
    form = MedicationOrderForm(medicines=medicines)

    if form.validate_on_submit():
        medicine = next((m for m in medicines if m.id == form.medicine_id.data), None)
        if medicine is None:
            flash('Bu derman elýeterli däl. Sanawy täzeläň.', 'danger')
            return redirect(url_for('inpatient.medications_add',
                                    hospitalization_id=hospitalization.id))

        planned_end_at = None
        if form.planned_end_at.data:
            # a plan is given as a day; the order runs to the end of it
            planned_end_at = datetime.combine(form.planned_end_at.data, time(23, 59))

        order = HospitalizationMedicationOrder(
            hospitalization_id=hospitalization.id,
            medicine_id=medicine.id,
            doctor_id=current_user.id,
            dose=form.dose.data.strip(),
            route=form.route.data,
            frequency=(form.frequency.data or '').strip() or None,
            quantity_per_dose=form.quantity_per_dose.data,
            planned_end_at=planned_end_at,
            note=(form.note.data or '').strip() or None,
        )
        db.session.add(order)
        db.session.commit()

        flash(f'«{medicine.name}» bellenildi.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/medications/add.html',
        form=form,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        medicines=medicines,
        quantities=stock_quantities_display(hospitalization.department_id, medicines),
        units={str(m.id): m.unit_display for m in medicines},
        back=back,
    )


@inpatient_bp.route('/bellenme/<int:order_id>/besetmek', methods=['POST'])
@inpatient_required(*MEDICATION_WRITER_ROLES)
def medications_stop(order_id):
    order = db.session.get(HospitalizationMedicationOrder, order_id)
    if order is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(order.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.medications', hospitalization_id=hospitalization.id)

    if not order.is_active:
        flash('Bu bellenme eýýäm bes edilen.', 'info')
        return redirect(back)

    order.status = HospitalizationMedicationOrder.STATUS_STOPPED
    order.stopped_at = datetime.now()
    order.stopped_by_id = current_user.id
    db.session.commit()

    flash(f'«{order.medicine.name}» bellenmesi bes edildi.', 'success')
    return redirect(back)


@inpatient_bp.route('/bellenme/<int:order_id>/bermek', methods=['POST'])
@inpatient_required('senior_nurse')
def medications_dispense(order_id):
    order = db.session.get(HospitalizationMedicationOrder, order_id)
    if order is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(order.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.medications', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — derman bermek bolmaýar.', 'danger')
        return redirect(back)

    # a drug may only leave the store against a live order of a doctor
    if not order.is_active:
        flash('Bu bellenme işjeň däl — derman bermek bolmaýar.', 'danger')
        return redirect(back)

    quantity = parse_quantity(request.form.get('quantity'))
    if quantity is None:
        flash('Dogry mukdary giriziň.', 'danger')
        return redirect(back)

    medicine = order.medicine
    stock_row = locked_stock(hospitalization.department_id, medicine.id)

    if stock_row.quantity < quantity:
        # read what we need before the rollback — it expires the objects, and a
        # stock row created just above would not survive it at all
        remaining, unit = format_quantity(stock_row.quantity), medicine.unit_display
        db.session.rollback()
        flash(f'Ammarda ýeterlik derman ýok. Galyndy: {remaining} {unit}.', 'danger')
        return redirect(back)

    dispense = HospitalizationMedicationDispense(
        order_id=order.id,
        hospitalization_id=hospitalization.id,
        medicine_id=medicine.id,
        department_id=hospitalization.department_id,
        quantity=quantity,
        price=medicine.price,
        is_insurance=medicine.is_insurance,
        given_at=datetime.now(),
        given_by_id=current_user.id,
        note=(request.form.get('note') or '').strip()[:500] or None,
    )
    db.session.add(dispense)
    db.session.flush()  # the journal row needs the dispense id

    apply_movement(stock_row, MedicineStockMovement.KIND_OUT, -quantity,
                   note=f'{hospitalization.history_number} · {hospitalization.patient.full_name}',
                   dispense=dispense)
    db.session.commit()

    flash(f'«{medicine.name}» — {format_quantity(quantity)} {medicine.unit_display} berildi. '
          f'Galyndy: {format_quantity(stock_row.quantity)}.', 'success')
    return redirect(back)


@inpatient_bp.route('/berilme/<int:dispense_id>/yzyna-almak', methods=['POST'])
@inpatient_required('senior_nurse')
def medications_dispense_cancel(dispense_id):
    # locked up front: two clicks on the same row must not refund twice
    dispense = (
        HospitalizationMedicationDispense.query
        .filter_by(id=dispense_id)
        .with_for_update()
        .first()
    )
    if dispense is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(dispense.hospitalization_id)
    if hospitalization is None:
        db.session.rollback()
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.medications', hospitalization_id=hospitalization.id)

    if not dispense.is_cancellable_by(current_user):
        already_cancelled = dispense.is_cancelled  # read before the rollback expires it
        db.session.rollback()
        if already_cancelled:
            flash('Bu berilme eýýäm yzyna alnan.', 'info')
        else:
            flash('Berilmäni diňe ony ýazan uly şepagat uýasy 24 sagadyň dowamynda '
                  'yzyna alyp bilýär.', 'danger')
        return redirect(back)

    cancelled_at = datetime.now()
    dispense.is_cancelled = True
    dispense.cancelled_at = cancelled_at
    dispense.cancelled_by_id = current_user.id

    # the amount goes back on the shelf through a compensating movement — the
    # original dispense stays in the journal, nothing is erased
    stock_row = locked_stock(dispense.department_id, dispense.medicine_id)
    apply_movement(stock_row, MedicineStockMovement.KIND_CORRECTION, dispense.quantity,
                   note=f'Yzyna alnan berilme #{dispense.id}', dispense=dispense)
    db.session.commit()

    flash(f'«{dispense.medicine.name}» berilmesi yzyna alyndy. '
          f'Galyndy: {format_quantity(stock_row.quantity)}.', 'success')
    return redirect(back)


# ── Diagnoses (diagnozlar) ────────────────────────────────────────────────────

# Diagnoses are the doctor's word — the same people who write the diary
DIAGNOSIS_WRITER_ROLES = DIARY_WRITER_ROLES


def can_write_diagnosis(hospitalization) -> bool:
    return (current_user.role in DIAGNOSIS_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


@inpatient_bp.route('/diagnozlar/<int:hospitalization_id>', methods=['GET', 'POST'])
@inpatient_main_required
def diagnoses(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    may_write = can_write_diagnosis(hospitalization)

    # the final diagnosis belongs to the discharge form — it is not written
    # loose here, or a stay could end up "final" while the patient still lies in
    allowed_kinds = (HospitalizationDiagnosis.KIND_PRELIMINARY,
                     HospitalizationDiagnosis.KIND_CLINICAL)
    form = DiagnosisForm(allowed_kinds=allowed_kinds) if may_write else None

    if may_write and form.validate_on_submit():
        if form.kind.data not in allowed_kinds:
            flash('Jemleýji diagnoz çykarylanda ýazylýar.', 'danger')
            return redirect(url_for('inpatient.diagnoses', hospitalization_id=hospitalization.id))

        hospitalization.diagnoses.append(HospitalizationDiagnosis(
            kind=form.kind.data,
            text=form.text.data.strip(),
            code=(form.code.data or '').strip() or None,
            note=(form.note.data or '').strip() or None,
            author_id=current_user.id,
        ))
        db.session.commit()
        flash('Diagnoz ýazyldy.', 'success')
        return redirect(url_for('inpatient.diagnoses', hospitalization_id=hospitalization.id))

    if request.method == 'POST' and not may_write:
        flash('Siz diagnoz ýazyp bilmeýärsiňiz.', 'danger')
        return redirect(url_for('inpatient.diagnoses', hospitalization_id=hospitalization.id))

    entries = (
        HospitalizationDiagnosis.query
        .options(joinedload(HospitalizationDiagnosis.author))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationDiagnosis.created_at.desc(),
                  HospitalizationDiagnosis.id.desc())
        .all()
    )

    return render_template(
        'inpatient/diagnoses/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        entries=entries,
        form=form,
        may_write=may_write,
        kinds=HospitalizationDiagnosis.KINDS,
    )


# ── Temperature sheet (temperatura sanawy) ────────────────────────────────────

# Measuring is the ward nurse's job; the senior nurse stands in for her
VITALS_WRITER_ROLES = ('nurse', 'senior_nurse')

VITALS_PER_PAGE = 40


def can_record_vitals(hospitalization) -> bool:
    return (current_user.role in VITALS_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


# Temperature chart geometry. The scale is fixed rather than fitted to the data
# so two patients' sheets are read the same way, and a flat normal line does not
# look like a wild swing.
CHART = {'min': 35.0, 'max': 41.0, 'width': 760.0, 'height': 150.0, 'left': 34.0, 'top': 12.0}


def temperature_chart(records):
    """Screen coordinates for the temperature curve, oldest reading first.

    Returns None when there is nothing to draw. Values outside the printed
    scale are clamped so one bad reading cannot push the curve off the card.
    """
    points = [r for r in records if r.temperature is not None]
    if not points:
        return None

    span = CHART['max'] - CHART['min']
    step = CHART['width'] / (len(points) - 1) if len(points) > 1 else 0.0

    dots = []
    for index, record in enumerate(points):
        value = min(max(float(record.temperature), CHART['min']), CHART['max'])
        x = CHART['left'] + (index * step if step else CHART['width'] / 2)
        y = CHART['top'] + CHART['height'] - (value - CHART['min']) / span * CHART['height']
        dots.append({
            'x': round(x, 1),
            'y': round(y, 1),
            'value': record.temperature_display,
            'when': record.measured_at.strftime('%d.%m %H:%M'),
            'fever': record.has_fever,
        })

    # the 37 °C line — where "normal" stops
    normal_y = CHART['top'] + CHART['height'] - (37.0 - CHART['min']) / span * CHART['height']

    return {
        'dots': dots,
        'polyline': ' '.join(f"{d['x']},{d['y']}" for d in dots),
        'normal_y': round(normal_y, 1),
        'grid': [
            {'label': f'{t:g}',
             'y': round(CHART['top'] + CHART['height']
                        - (t - CHART['min']) / span * CHART['height'], 1)}
            for t in (35, 36, 37, 38, 39, 40, 41)
        ],
        'view_width': CHART['left'] + CHART['width'] + 16,
        'view_height': CHART['top'] + CHART['height'] + 28,
    }


@inpatient_bp.route('/olcegler/<int:hospitalization_id>', methods=['GET', 'POST'])
@inpatient_main_required
def vitals(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    may_record = can_record_vitals(hospitalization)
    form = VitalRecordForm() if may_record else None

    if may_record and form.validate_on_submit():
        db.session.add(HospitalizationVitalRecord(
            hospitalization_id=hospitalization.id,
            measured_at=form.measured_at.data,
            temperature=form.temperature.data,
            pulse=form.pulse.data,
            systolic=form.systolic.data,
            diastolic=form.diastolic.data,
            respiratory_rate=form.respiratory_rate.data,
            note=(form.note.data or '').strip() or None,
            recorded_by_id=current_user.id,
        ))
        db.session.commit()
        flash('Ölçegler ýazyldy.', 'success')
        return redirect(url_for('inpatient.vitals', hospitalization_id=hospitalization.id))

    if request.method == 'POST' and not may_record:
        flash('Siz ölçeg ýazyp bilmeýärsiňiz.', 'danger')
        return redirect(url_for('inpatient.vitals', hospitalization_id=hospitalization.id))

    if may_record and request.method == 'GET':
        form.measured_at.data = datetime.now().replace(second=0, microsecond=0)

    page = request.args.get('page', 1, type=int)
    pagination = (
        HospitalizationVitalRecord.query
        .options(joinedload(HospitalizationVitalRecord.recorded_by))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationVitalRecord.measured_at.desc(),
                  HospitalizationVitalRecord.id.desc())
        .paginate(page=page, per_page=VITALS_PER_PAGE, error_out=False)
    )

    return render_template(
        'inpatient/vitals/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        records=pagination.items,
        pagination=pagination,
        # the chart reads left-to-right in time, the table newest-first
        chart=temperature_chart(list(reversed(pagination.items))),
        form=form,
        may_record=may_record,
    )


@inpatient_bp.route('/olcegler/yazgy/<int:record_id>', methods=['GET', 'POST'])
@inpatient_required(*VITALS_WRITER_ROLES)
def vitals_edit(record_id):
    record = db.session.get(HospitalizationVitalRecord, record_id)
    if record is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(record.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.vitals', hospitalization_id=hospitalization.id)

    if not record.is_editable_by(current_user):
        flash('Ýazgyny diňe ony ýazan işgär 12 sagadyň dowamynda üýtgedip bilýär.', 'danger')
        return redirect(back)

    form = VitalRecordForm(obj=record)

    if form.validate_on_submit():
        record.measured_at = form.measured_at.data
        record.temperature = form.temperature.data
        record.pulse = form.pulse.data
        record.systolic = form.systolic.data
        record.diastolic = form.diastolic.data
        record.respiratory_rate = form.respiratory_rate.data
        record.note = (form.note.data or '').strip() or None
        record.updated_at = datetime.now()
        db.session.commit()
        flash('Ölçegler üýtgedildi.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/vitals/edit.html',
        form=form,
        record=record,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


# ── Operations (operasiýalar) ─────────────────────────────────────────────────

# Planning and writing up an operation is the doctor's act
OPERATION_WRITER_ROLES = ('doctor', 'department_head')


def can_manage_operations(hospitalization) -> bool:
    return (current_user.role in OPERATION_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


def active_operations():
    return Operation.query.filter_by(is_active=True).order_by(Operation.name).all()


def _operation_status(form):
    """Filling in `performed_at` is what turns a plan into a record."""
    return (HospitalizationOperation.STATUS_DONE if form.performed_at.data
            else HospitalizationOperation.STATUS_PLANNED)


@inpatient_bp.route('/operasiyalar/<int:hospitalization_id>')
@inpatient_main_required
def operations(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    rows = (
        HospitalizationOperation.query
        .options(joinedload(HospitalizationOperation.operation),
                 joinedload(HospitalizationOperation.surgeon),
                 joinedload(HospitalizationOperation.anesthesiologist),
                 joinedload(HospitalizationOperation.created_by),
                 joinedload(HospitalizationOperation.cancelled_by),
                 subqueryload(HospitalizationOperation.assistants))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationOperation.created_at.desc())
        .all()
    )

    return render_template(
        'inpatient/operations/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        planned=[o for o in rows if o.is_planned],
        done=[o for o in rows if o.is_done],
        cancelled=[o for o in rows
                   if o.status == HospitalizationOperation.STATUS_CANCELLED],
        may_manage=can_manage_operations(hospitalization),
    )


def _save_operation(form, hospitalization, operations_list, medics, record=None):
    """Write a planned or performed operation. Returns the row, or None if the
    submitted ids did not survive the re-check against the catalogue."""
    operation = next((o for o in operations_list if o.id == form.operation_id.data), None)
    surgeon = next((m for m in medics if m.id == form.surgeon_id.data), None)
    if operation is None or surgeon is None:
        return None

    anesthesiologist_id = form.anesthesiologist_id.data or None
    if anesthesiologist_id and not any(m.id == anesthesiologist_id for m in medics):
        return None

    assistants = [m for m in medics if m.id in set(form.assistant_ids.data or [])]

    if record is None:
        record = HospitalizationOperation(
            hospitalization_id=hospitalization.id,
            created_by_id=current_user.id,
            # snapshotted once, at the moment the record is opened — a later
            # catalogue change must not rewrite what this operation cost
            price=operation.price,
            is_insurance=operation.is_insurance,
        )
        db.session.add(record)

    record.operation_id = operation.id
    record.surgeon_id = surgeon.id
    record.anesthesiologist_id = anesthesiologist_id
    record.anesthesia = form.anesthesia.data
    record.planned_at = form.planned_at.data
    record.performed_at = form.performed_at.data
    record.indication = (form.indication.data or '').strip() or None
    record.protocol = (form.protocol.data or '').strip() or None
    record.complications = (form.complications.data or '').strip() or None
    record.assistants = assistants

    new_status = _operation_status(form)
    if new_status == HospitalizationOperation.STATUS_DONE:
        record.performed_by_id = current_user.id
    record.status = new_status
    return record


@inpatient_bp.route('/operasiyalar/<int:hospitalization_id>/goshmak', methods=['GET', 'POST'])
@inpatient_required(*OPERATION_WRITER_ROLES)
def operations_add(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.operations', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — operasiýa ýazmak bolmaýar.', 'danger')
        return redirect(back)

    catalogue = active_operations()
    medics = department_medics(hospitalization.department_id)
    form = OperationForm(operations=catalogue, medics=medics)

    if request.method == 'GET':
        form.surgeon_id.data = hospitalization.doctor_id or (medics[0].id if medics else None)

    if form.validate_on_submit():
        record = _save_operation(form, hospitalization, catalogue, medics)
        if record is None:
            flash('Saýlananlaryň biri elýeterli däl. Sahypany täzeläň.', 'danger')
            return redirect(url_for('inpatient.operations_add',
                                    hospitalization_id=hospitalization.id))
        db.session.commit()
        flash(f'«{record.operation.name}» ýazyldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/operations/form.html',
        form=form,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        catalogue=catalogue,
        medics=medics,
        record=None,
        back=back,
    )


@inpatient_bp.route('/operasiya/<int:operation_id>/uytgetmek', methods=['GET', 'POST'])
@inpatient_required(*OPERATION_WRITER_ROLES)
def operations_edit(operation_id):
    record = db.session.get(HospitalizationOperation, operation_id)
    if record is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(record.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.operations', hospitalization_id=hospitalization.id)

    if record.status == HospitalizationOperation.STATUS_CANCELLED:
        flash('Ýatyrylan operasiýany üýtgedip bolmaýar.', 'danger')
        return redirect(back)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — operasiýany üýtgedip bolmaýar.', 'danger')
        return redirect(back)

    catalogue = active_operations()
    # the catalogue row this record points at may have been blocked since; keep
    # it selectable so editing does not silently change the operation
    if not any(o.id == record.operation_id for o in catalogue):
        catalogue = [record.operation] + catalogue
    medics = department_medics(hospitalization.department_id)
    if not any(m.id == record.surgeon_id for m in medics):
        medics = [record.surgeon] + medics

    form = OperationForm(operations=catalogue, medics=medics)

    if not form.is_submitted():
        form.operation_id.data = record.operation_id
        form.surgeon_id.data = record.surgeon_id
        form.anesthesiologist_id.data = record.anesthesiologist_id or 0
        form.assistant_ids.data = [u.id for u in record.assistants]
        form.anesthesia.data = record.anesthesia
        form.planned_at.data = record.planned_at
        form.performed_at.data = record.performed_at
        form.indication.data = record.indication
        form.protocol.data = record.protocol
        form.complications.data = record.complications

    if form.validate_on_submit():
        saved = _save_operation(form, hospitalization, catalogue, medics, record=record)
        if saved is None:
            flash('Saýlananlaryň biri elýeterli däl. Sahypany täzeläň.', 'danger')
            return redirect(url_for('inpatient.operations_edit', operation_id=record.id))
        db.session.commit()
        flash(f'«{record.operation.name}» täzelendi.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/operations/form.html',
        form=form,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        catalogue=catalogue,
        medics=medics,
        record=record,
        back=back,
    )


@inpatient_bp.route('/operasiya/<int:operation_id>/yatyrmak', methods=['GET', 'POST'])
@inpatient_required(*OPERATION_WRITER_ROLES)
def operations_cancel(operation_id):
    record = db.session.get(HospitalizationOperation, operation_id)
    if record is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(record.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.operations', hospitalization_id=hospitalization.id)

    # only a plan may be called off — an operation that happened is a fact
    if not record.is_planned:
        flash('Diňe meýilleşdirilen operasiýany ýatyryp bolýar.', 'danger')
        return redirect(back)

    form = OperationCancelForm()

    if form.validate_on_submit():
        record.status = HospitalizationOperation.STATUS_CANCELLED
        record.cancelled_at = datetime.now()
        record.cancelled_by_id = current_user.id
        record.cancel_reason = form.reason.data.strip()
        db.session.commit()
        flash(f'«{record.operation.name}» ýatyryldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/operations/cancel.html',
        form=form,
        record=record,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


# ── Admission examination (ilkinji gözden geçirme) ────────────────────────────

# The opening document of the case history — the doctor's word, like the diary
ADMISSION_EXAM_WRITER_ROLES = DIARY_WRITER_ROLES

# Allergies are asked about by the doctor, but the senior nurse hears about a
# reaction at the moment she hands a drug over — she must be able to write it down
ALLERGY_WRITER_ROLES = ('doctor', 'department_head', 'senior_nurse')


def can_write_admission_exam(hospitalization) -> bool:
    return (current_user.role in ADMISSION_EXAM_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


def can_edit_allergies(hospitalization) -> bool:
    return (current_user.role in ALLERGY_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


def _apply_admission_exam(form, exam):
    exam.complaints = form.complaints.data.strip()
    exam.anamnesis_morbi = form.anamnesis_morbi.data.strip()
    exam.anamnesis_vitae = (form.anamnesis_vitae.data or '').strip() or None
    exam.objective_status = form.objective_status.data.strip()
    exam.local_status = (form.local_status.data or '').strip() or None
    exam.diagnosis_rationale = (form.diagnosis_rationale.data or '').strip() or None
    exam.examination_plan = (form.examination_plan.data or '').strip() or None
    exam.treatment_plan = (form.treatment_plan.data or '').strip() or None
    exam.temperature = form.temperature.data
    exam.pulse = form.pulse.data
    exam.systolic = form.systolic.data
    exam.diastolic = form.diastolic.data
    exam.height = form.height.data
    exam.weight = form.weight.data


@inpatient_bp.route('/gozden-gecirme/<int:hospitalization_id>', methods=['GET', 'POST'])
@inpatient_main_required
def admission_exam(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    patient = hospitalization.patient
    exam = hospitalization.admission_exam
    # one exam per stay: once it exists, writing means editing it
    may_write = exam is None and can_write_admission_exam(hospitalization)

    form = AdmissionExamForm() if may_write else None
    allergy_form = AllergyForm() if can_edit_allergies(hospitalization) else None

    if may_write and form.validate_on_submit():
        exam = HospitalizationAdmissionExam(
            hospitalization_id=hospitalization.id,
            author_id=current_user.id,
        )
        _apply_admission_exam(form, exam)
        db.session.add(exam)
        try:
            db.session.commit()
        except IntegrityError:
            # two doctors opened the blank form at once — the unique index
            # rejects the second, and their text would otherwise be lost
            db.session.rollback()
            flash('Bu ýatyş üçin gözden geçirme eýýäm ýazyldy.', 'warning')
        else:
            flash('Ilkinji gözden geçirme ýazyldy.', 'success')
        return redirect(url_for('inpatient.admission_exam',
                                hospitalization_id=hospitalization.id))

    if request.method == 'POST' and not may_write:
        flash('Siz gözden geçirme ýazyp bilmeýärsiňiz.', 'danger')
        return redirect(url_for('inpatient.admission_exam',
                                hospitalization_id=hospitalization.id))

    return render_template(
        'inpatient/admission/exam.html',
        hospitalization=hospitalization,
        patient=patient,
        exam=exam,
        form=form,
        allergy_form=allergy_form,
        may_write=may_write,
        may_edit_allergies=can_edit_allergies(hospitalization),
        severities=PatientAllergy.SEVERITIES,
    )


@inpatient_bp.route('/gozden-gecirme/<int:exam_id>/uytgetmek', methods=['GET', 'POST'])
@inpatient_required(*ADMISSION_EXAM_WRITER_ROLES)
def admission_exam_edit(exam_id):
    exam = db.session.get(HospitalizationAdmissionExam, exam_id)
    if exam is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(exam.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.admission_exam', hospitalization_id=hospitalization.id)

    if not exam.is_editable_by(current_user):
        flash('Gözden geçirmäni diňe awtory ýazylandan soň 24 sagadyň dowamynda '
              'üýtgedip bilýär.', 'danger')
        return redirect(back)

    form = AdmissionExamForm(obj=exam)

    if form.validate_on_submit():
        _apply_admission_exam(form, exam)
        exam.updated_at = datetime.now()
        db.session.commit()
        flash('Gözden geçirme üýtgedildi.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/admission/edit.html',
        form=form,
        exam=exam,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


# ── Allergies (allergiýa) ─────────────────────────────────────────────────────

@inpatient_bp.route('/allergiya/<int:hospitalization_id>/goshmak', methods=['POST'])
@inpatient_required(*ALLERGY_WRITER_ROLES)
def allergies_add(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.admission_exam', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — allergiýa goşmak bolmaýar.', 'danger')
        return redirect(back)

    form = AllergyForm()
    if not form.validate_on_submit():
        for field in form:
            for error in field.errors:
                flash(error, 'danger')
        return redirect(back)

    patient = hospitalization.patient
    substance = form.substance.data.strip()

    if any(a.substance.lower() == substance.lower() for a in patient.active_allergies):
        flash(f'«{substance}» eýýäm hasaba alnan.', 'info')
        return redirect(back)

    patient.allergies.append(PatientAllergy(
        substance=substance,
        reaction=(form.reaction.data or '').strip() or None,
        severity=form.severity.data,
        note=(form.note.data or '').strip() or None,
        recorded_by_id=current_user.id,
    ))
    # writing one down is itself an answer to "was this asked?"
    patient.allergies_reviewed_at = datetime.now()
    patient.allergies_reviewed_by_id = current_user.id
    db.session.commit()

    flash(f'Allergiýa «{substance}» hasaba alyndy.', 'success')
    return redirect(back)


@inpatient_bp.route('/allergiya/<int:hospitalization_id>/yok', methods=['POST'])
@inpatient_required(*ALLERGY_WRITER_ROLES)
def allergies_mark_none(hospitalization_id):
    """Record that allergies were asked about and none were found. Without this
    an empty list is indistinguishable from nobody having asked."""
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.admission_exam', hospitalization_id=hospitalization.id)
    patient = hospitalization.patient

    if patient.active_allergies:
        flash('Syrkawda hasaba alnan allergiýa bar — ilki ony aýyryň.', 'danger')
        return redirect(back)

    patient.allergies_reviewed_at = datetime.now()
    patient.allergies_reviewed_by_id = current_user.id
    db.session.commit()

    flash('Allergiýa ýok diýip bellenildi.', 'success')
    return redirect(back)


@inpatient_bp.route('/allergiya/<int:allergy_id>/ayyrmak', methods=['GET', 'POST'])
@inpatient_required(*ALLERGY_WRITER_ROLES)
def allergies_remove(allergy_id):
    allergy = db.session.get(PatientAllergy, allergy_id)
    if allergy is None:
        abort(404)

    # the patient must be lying in one of the user's departments right now
    hospitalization = active_hospitalization(allergy.patient_id)
    if hospitalization is None or hospitalization.department_id not in set(user_department_ids()):
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.admission_exam', hospitalization_id=hospitalization.id)

    if not allergy.is_active:
        flash('Bu allergiýa eýýäm aýrylan.', 'info')
        return redirect(back)

    form = AllergyRemoveForm()

    if form.validate_on_submit():
        allergy.is_active = False
        allergy.removed_at = datetime.now()
        allergy.removed_by_id = current_user.id
        allergy.remove_reason = form.reason.data.strip()
        db.session.commit()
        flash(f'Allergiýa «{allergy.substance}» aýryldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/admission/allergy_remove.html',
        form=form,
        allergy=allergy,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


# ── Examination orders: analyses, studies, blanks ─────────────────────────────

# The catalogues are shared with the outpatient section, the orders are not:
# nothing here is attached to an Examination and nothing goes through the
# cashier. Ordering is the doctor's word, like the diary and the drug orders.
ORDER_WRITER_ROLES = ('doctor', 'department_head')

# The three order tables have the same shape, so one set of routes serves all
# three; `kind` in the URL picks the table. Keeping them apart in the database
# (and together in the routes) mirrors how the outpatient side stores its own
# analysis / tool / blank lines.
ORDER_KINDS = {
    'analiz': {
        'model': HospitalizationAnalysisOrder,
        'catalogue': Analysis,
        'label': 'Analiz',
        'relation': 'analysis_orders',
        'fk': 'analysis_id',
    },
    'barlag': {
        'model': HospitalizationToolOrder,
        'catalogue': AnalysisTool,
        'label': 'Instrumental barlag',
        'relation': 'tool_orders',
        'fk': 'tool_id',
    },
    'blank': {
        'model': HospitalizationBlankOrder,
        'catalogue': Blank,
        'label': 'Blank',
        'relation': 'blank_orders',
        'fk': 'blank_id',
    },
}


def can_order_examinations(hospitalization) -> bool:
    """Doctors and the head of that department order; everyone else reads."""
    return (current_user.role in ORDER_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


def can_record_order_result(hospitalization) -> bool:
    """Results are written by the ward itself — the lab has no access here, so
    whoever types the finding signs it."""
    return can_order_examinations(hospitalization)


def _order_kind(kind):
    spec = ORDER_KINDS.get(kind)
    if spec is None:
        abort(404)
    return spec


def _load_order(kind, order_id):
    """An order plus the stay it belongs to, both checked against the viewer's
    departments. Returns (spec, record, hospitalization) or aborts/None."""
    spec = _order_kind(kind)
    record = db.session.get(spec['model'], order_id)
    if record is None:
        abort(404)
    hospitalization = _load_visible_hospitalization(record.hospitalization_id)
    return spec, record, hospitalization


def order_catalogue(kind):
    """Active catalogue rows of one kind, in the order a doctor scans them."""
    model = ORDER_KINDS[kind]['catalogue']
    query = model.query.filter_by(is_active=True)
    if kind == 'analiz':
        query = query.options(joinedload(Analysis.responsible))
    elif kind == 'barlag':
        query = query.options(joinedload(AnalysisTool.category),
                              joinedload(AnalysisTool.subcategory))
    return query.order_by(model.name).all()


def active_combined_analyses():
    """Ready-made panels, each with the analyses that would actually be ordered.

    Ordering a panel writes its analyses as separate rows — what is carried out
    and priced is the analysis, not the panel. A blocked analysis is left out of
    both the list and the sum, so the doctor is not shown a line that will
    quietly not happen; a panel with nothing active left is not offered at all.
    """
    panels = []
    rows = (
        CombinedAnalysis.query
        .filter_by(is_active=True)
        .options(subqueryload(CombinedAnalysis.analyses))
        .order_by(CombinedAnalysis.name)
        .all()
    )
    for panel in rows:
        analyses = [a for a in panel.analyses if a.is_active]
        if analyses:
            panels.append({
                'panel': panel,
                'analyses': analyses,
                'total': sum(a.price for a in analyses),
            })
    return panels


def _order_price(kind, row):
    """What one unit of a catalogue row costs. Tools and blanks keep their price
    in `total_price`; that is the price of one study, and the count is the
    order's own quantity."""
    return row.price if kind == 'analiz' else row.total_price


@inpatient_bp.route('/barlaglar/<int:hospitalization_id>')
@inpatient_main_required
def orders(hospitalization_id):
    """Everything ordered for this stay — outstanding first, then what came
    back, then what was called off."""
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    # (kind, record) pairs — the page needs the kind to build links back into
    # the right table, and the three tables are shown as one worklist
    rows = []
    for kind, spec in ORDER_KINDS.items():
        rows += [(kind, row) for row in getattr(hospitalization, spec['relation'])]
    rows.sort(key=lambda pair: pair[1].ordered_at, reverse=True)

    return render_template(
        'inpatient/orders/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        pending=[pair for pair in rows if pair[1].is_ordered],
        completed=[pair for pair in rows if pair[1].is_completed],
        cancelled=[pair for pair in rows if pair[1].is_cancelled],
        may_order=can_order_examinations(hospitalization),
        may_record=can_record_order_result(hospitalization),
    )


@inpatient_bp.route('/barlaglar/<int:hospitalization_id>/goshmak', methods=['GET', 'POST'])
@inpatient_required(*ORDER_WRITER_ROLES)
def orders_add(hospitalization_id):
    """One page for all three catalogues: tick what is needed, set how many.

    Every submitted id is re-checked against the active catalogue — a page left
    open while an item was blocked must produce a message, not a crash.
    """
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.orders', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — barlag bellemek bolmaýar.', 'danger')
        return redirect(back)

    catalogues = {kind: order_catalogue(kind) for kind in ORDER_KINDS}
    combined = active_combined_analyses()

    if request.method == 'POST':
        note = (request.form.get('note') or '').strip()[:500] or None
        errors = []
        created = 0

        # A panel is expanded into its analyses; a panel whose analysis is also
        # ticked separately must not produce the row twice, so the panel that
        # brought an analysis in is remembered per analysis id.
        panel_of = {}
        combined_by_id = {entry['panel'].id: entry for entry in combined}
        for cid in dict.fromkeys(request.form.getlist('combined_ids', type=int)):
            entry = combined_by_id.get(cid)
            if entry is None:
                errors.append('Saýlanan toplumlaryň käbiri elýeterli däl.')
                continue
            for analysis in entry['analyses']:
                panel_of.setdefault(analysis.id, cid)

        for kind, spec in ORDER_KINDS.items():
            by_id = {row.id: row for row in catalogues[kind]}
            picked = dict.fromkeys(request.form.getlist(f'{kind}_ids', type=int))
            if kind == 'analiz':
                # analyses pulled in by a panel are ordered even if not ticked
                picked = dict.fromkeys(list(picked) + [aid for aid in panel_of
                                                       if aid not in picked])

            for item_id in picked:
                row = by_id.get(item_id)
                if row is None:
                    errors.append(f'Saýlanan «{spec["label"]}» elýeterli däl ýa-da bloklanan.')
                    continue

                quantity = max(1, request.form.get(f'{kind}_qty_{item_id}', 1, type=int))
                order = spec['model'](
                    hospitalization_id=hospitalization.id,
                    quantity=quantity,
                    # snapshotted at ordering, like every other priced row of a
                    # stay — a later catalogue change must not rewrite this
                    price=_order_price(kind, row),
                    is_insurance=row.is_insurance,
                    note=note,
                    ordered_by_id=current_user.id,
                    **{spec['fk']: row.id},
                )
                if kind == 'analiz' and item_id in panel_of:
                    order.combined_analysis_id = panel_of[item_id]
                db.session.add(order)
                created += 1

        if not created:
            for message in dict.fromkeys(errors):
                flash(message, 'danger')
            if not errors:
                flash('Iň bolmanda bir barlag saýlaň.', 'warning')
            return redirect(url_for('inpatient.orders_add',
                                    hospitalization_id=hospitalization.id))

        db.session.commit()
        for message in dict.fromkeys(errors):
            flash(message, 'warning')
        flash(f'{created} sany barlag bellenildi.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/orders/add.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        catalogues=catalogues,
        combined=combined,
        kinds=ORDER_KINDS,
        back=back,
    )


@inpatient_bp.route('/barlag/<kind>/<int:order_id>/netije', methods=['GET', 'POST'])
@inpatient_required(*ORDER_WRITER_ROLES)
def orders_result(kind, order_id):
    """Writing down what came back. An order carries its result once; a
    correction is an edit of the same row, since the finding is one fact."""
    spec, record, hospitalization = _load_order(kind, order_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.orders', hospitalization_id=hospitalization.id)

    if record.is_cancelled:
        flash('Ýatyrylan barlaga netije ýazyp bolmaýar.', 'danger')
        return redirect(back)

    if not can_record_order_result(hospitalization):
        flash('Siz bu barlaga netije ýazyp bilmeýärsiňiz.', 'danger')
        return redirect(back)

    form = OrderResultForm()

    if request.method == 'GET':
        form.result.data = record.result
        form.completed_at.data = record.completed_at or datetime.now().replace(second=0, microsecond=0)

    if form.validate_on_submit():
        record.result = form.result.data.strip()
        record.completed_at = form.completed_at.data or datetime.now()
        record.completed_by_id = current_user.id
        record.status = spec['model'].STATUS_COMPLETED
        db.session.commit()
        flash(f'«{record.name_display}» netijesi ýazyldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/orders/result.html',
        form=form,
        record=record,
        kind=kind,
        label=spec['label'],
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


@inpatient_bp.route('/barlag/<kind>/<int:order_id>/yatyrmak', methods=['GET', 'POST'])
@inpatient_required(*ORDER_WRITER_ROLES)
def orders_cancel(kind, order_id):
    """Calling off an order nobody carried out yet."""
    spec, record, hospitalization = _load_order(kind, order_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.orders', hospitalization_id=hospitalization.id)

    # a result that is already on record is a fact, not a plan
    if not record.is_ordered:
        flash('Diňe ýerine ýetirilmedik barlagy ýatyryp bolýar.', 'danger')
        return redirect(back)

    if not can_order_examinations(hospitalization):
        flash('Siz bu barlagy ýatyryp bilmeýärsiňiz.', 'danger')
        return redirect(back)

    form = OrderCancelForm()

    if form.validate_on_submit():
        record.status = spec['model'].STATUS_CANCELLED
        record.cancelled_at = datetime.now()
        record.cancelled_by_id = current_user.id
        record.cancel_reason = form.reason.data.strip()
        db.session.commit()
        flash(f'«{record.name_display}» ýatyryldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/orders/cancel.html',
        form=form,
        record=record,
        label=spec['label'],
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


# ── Consultations ─────────────────────────────────────────────────────────────

# Who may call a specialist in and write down what they said. The consultant
# themselves is not given access to another department's case history — see
# HospitalizationConsultation.
CONSULTATION_WRITER_ROLES = ORDER_WRITER_ROLES


def can_manage_consultations(hospitalization) -> bool:
    return (current_user.role in CONSULTATION_WRITER_ROLES
            and hospitalization.department_id in set(user_department_ids())
            and hospitalization.is_open)


def consultation_choices():
    """(directions, doctors, allowed) for the consultation form.

    Only ugurlar that somebody can actually take are offered: which doctor
    holds which ugur is set in the admin section, and an ugur with nobody
    behind it would be a dead end in the form.
    """
    doctors = (
        User.query
        .filter(User.role.in_(('doctor', 'department_head')),
                User.is_active == True)  # noqa: E712
        .options(subqueryload(User.directions))
        .order_by(User.full_name)
        .all()
    )

    allowed = {}
    for doctor in doctors:
        for direction in doctor.directions:
            if direction.is_active:
                allowed.setdefault(direction.id, set()).add(doctor.id)

    directions = (
        DoctorDirection.query
        .filter(DoctorDirection.is_active == True,  # noqa: E712
                DoctorDirection.id.in_(allowed.keys() or [0]))
        .order_by(DoctorDirection.name)
        .all()
    )
    offered = {d.id for d in directions}
    doctors = [d for d in doctors
               if any(direction.id in offered for direction in d.directions)]
    return directions, doctors, allowed


@inpatient_bp.route('/konsultasiyalar/<int:hospitalization_id>')
@inpatient_main_required
def consultations(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    rows = (
        HospitalizationConsultation.query
        .options(joinedload(HospitalizationConsultation.direction),
                 joinedload(HospitalizationConsultation.doctor),
                 joinedload(HospitalizationConsultation.ordered_by),
                 joinedload(HospitalizationConsultation.completed_by),
                 joinedload(HospitalizationConsultation.cancelled_by))
        .filter_by(hospitalization_id=hospitalization.id)
        .order_by(HospitalizationConsultation.ordered_at.desc())
        .all()
    )

    return render_template(
        'inpatient/consultations/list.html',
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        pending=[c for c in rows if c.is_ordered],
        completed=[c for c in rows if c.is_completed],
        cancelled=[c for c in rows if c.is_cancelled],
        may_manage=can_manage_consultations(hospitalization),
    )


@inpatient_bp.route('/konsultasiyalar/<int:hospitalization_id>/goshmak', methods=['GET', 'POST'])
@inpatient_required(*CONSULTATION_WRITER_ROLES)
def consultations_add(hospitalization_id):
    hospitalization = _load_visible_hospitalization(hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.consultations', hospitalization_id=hospitalization.id)

    if not hospitalization.is_open:
        flash('Syrkaw çykarylan — konsultasiýa bellemek bolmaýar.', 'danger')
        return redirect(back)

    directions, doctors, allowed = consultation_choices()
    if not directions:
        flash('Ugurlara lukman bellenmedik. Dolandyryjy ilki ugurlary lukmanlara bellemeli.',
              'warning')
        return redirect(back)

    form = ConsultationForm(directions=directions, doctors=doctors, allowed=allowed)

    if form.validate_on_submit():
        direction = next((d for d in directions if d.id == form.direction_id.data), None)
        if direction is None:
            flash('Saýlanan ugur elýeterli däl. Sahypany täzeläň.', 'danger')
            return redirect(url_for('inpatient.consultations_add',
                                    hospitalization_id=hospitalization.id))

        record = HospitalizationConsultation(
            hospitalization_id=hospitalization.id,
            direction_id=direction.id,
            doctor_id=form.doctor_id.data,
            # snapshotted at ordering, like every other priced row of a stay
            price=direction.price,
            is_insurance=direction.is_insurance,
            reason=(form.reason.data or '').strip() or None,
            ordered_by_id=current_user.id,
        )
        db.session.add(record)
        db.session.commit()
        flash(f'«{direction.name}» konsultasiýasy bellenildi.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/consultations/form.html',
        form=form,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        directions=directions,
        doctors=doctors,
        allowed={did: sorted(ids) for did, ids in allowed.items()},
        back=back,
    )


@inpatient_bp.route('/konsultasiya/<int:consultation_id>/netije', methods=['GET', 'POST'])
@inpatient_required(*CONSULTATION_WRITER_ROLES)
def consultations_conclusion(consultation_id):
    """The specialist's finding, written down by the ward over their name."""
    record = db.session.get(HospitalizationConsultation, consultation_id)
    if record is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(record.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.consultations', hospitalization_id=hospitalization.id)

    if record.is_cancelled:
        flash('Ýatyrylan konsultasiýa netije ýazyp bolmaýar.', 'danger')
        return redirect(back)

    if not can_manage_consultations(hospitalization):
        flash('Siz bu konsultasiýa netije ýazyp bilmeýärsiňiz.', 'danger')
        return redirect(back)

    form = ConsultationConclusionForm()

    if request.method == 'GET':
        form.conclusion.data = record.conclusion
        form.performed_at.data = record.performed_at or datetime.now().replace(second=0, microsecond=0)

    if form.validate_on_submit():
        record.conclusion = form.conclusion.data.strip()
        record.performed_at = form.performed_at.data or datetime.now()
        record.completed_at = datetime.now()
        record.completed_by_id = current_user.id
        record.status = HospitalizationConsultation.STATUS_COMPLETED
        db.session.commit()
        flash(f'«{record.direction.name}» konsultasiýasynyň netijesi ýazyldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/consultations/conclusion.html',
        form=form,
        record=record,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )


@inpatient_bp.route('/konsultasiya/<int:consultation_id>/yatyrmak', methods=['GET', 'POST'])
@inpatient_required(*CONSULTATION_WRITER_ROLES)
def consultations_cancel(consultation_id):
    record = db.session.get(HospitalizationConsultation, consultation_id)
    if record is None:
        abort(404)

    hospitalization = _load_visible_hospitalization(record.hospitalization_id)
    if hospitalization is None:
        flash('Bu syrkaw siziň bölümiňizde ýatmaýar.', 'danger')
        return redirect(url_for('inpatient.patients_list'))

    back = url_for('inpatient.consultations', hospitalization_id=hospitalization.id)

    if not record.is_ordered:
        flash('Diňe geçirilmedik konsultasiýany ýatyryp bolýar.', 'danger')
        return redirect(back)

    if not can_manage_consultations(hospitalization):
        flash('Siz bu konsultasiýany ýatyryp bilmeýärsiňiz.', 'danger')
        return redirect(back)

    form = OrderCancelForm()

    if form.validate_on_submit():
        record.status = HospitalizationConsultation.STATUS_CANCELLED
        record.cancelled_at = datetime.now()
        record.cancelled_by_id = current_user.id
        record.cancel_reason = form.reason.data.strip()
        db.session.commit()
        flash(f'«{record.direction.name}» konsultasiýasy ýatyryldy.', 'success')
        return redirect(back)

    return render_template(
        'inpatient/consultations/cancel.html',
        form=form,
        record=record,
        hospitalization=hospitalization,
        patient=hospitalization.patient,
        back=back,
    )
