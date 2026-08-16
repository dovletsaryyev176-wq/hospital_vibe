from datetime import datetime
from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, logout_user
from sqlalchemy.orm import joinedload, subqueryload
from app.inpatient import inpatient_bp
from app.inpatient.forms import (HospitalizationForm, BedAssignmentForm,
                                 DoctorAssignmentForm, DiaryEntryForm, valid_phone)
from app.extensions import db
from app.models import (Room, Bed, Meal, Patient, User, Hospitalization, HospitalizationRelative,
                        HospitalizationBedStay, HospitalizationDoctorAssignment,
                        HospitalizationDiaryEntry, HospitalizationMealAssignment,
                        user_departments, meal_departments)


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


# ── Dashboard ─────────────────────────────────────────────────────────────────

@inpatient_bp.route('/')
@inpatient_bp.route('/dashboard')
@inpatient_main_required
def dashboard():
    departments = current_user.active_departments
    dep_ids = [d.id for d in departments]

    room_counts = {}
    bed_counts = {}
    if dep_ids:
        rows = (
            db.session.query(Room.department_id, db.func.count(Room.id))
            .filter(Room.department_id.in_(dep_ids), Room.is_active == True)  # noqa: E712
            .group_by(Room.department_id)
            .all()
        )
        room_counts = dict(rows)

        rows = (
            db.session.query(Room.department_id, db.func.count(Bed.id))
            .join(Bed, Bed.room_id == Room.id)
            .filter(Room.department_id.in_(dep_ids),
                    Room.is_active == True, Bed.is_active == True)  # noqa: E712
            .group_by(Room.department_id)
            .all()
        )
        bed_counts = dict(rows)

    return render_template(
        'inpatient/dashboard.html',
        departments=departments,
        room_counts=room_counts,
        bed_counts=bed_counts,
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
            db.session.add(hospitalization)
            db.session.commit()
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


@inpatient_bp.route('/syrkawlar/<int:patient_id>/cykarmak', methods=['POST'])
@inpatient_required('department_head')
def patients_discharge(patient_id):
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

    discharged_at = datetime.now()
    current.status = Hospitalization.STATUS_DISCHARGED
    current.discharged_at = discharged_at
    current.discharged_by_id = current_user.id

    open_stay = current.current_bed_stay
    if open_stay is not None:
        open_stay.ended_at = discharged_at

    open_doctor = current.current_doctor_assignment
    if open_doctor is not None:
        open_doctor.ended_at = discharged_at

    for meal_assignment in current.active_meal_assignments:
        meal_assignment.ended_at = discharged_at
        meal_assignment.ended_by_id = current_user.id

    db.session.commit()

    flash(f'«{patient.full_name}» ýatymlaýyn bölümden çykaryldy.', 'success')
    return redirect(url_for('inpatient.patients_list'))


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
        flash('Ýazgyny diňe awtory we ýazylan gününde üýtgedip bolýar.', 'danger')
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
