from datetime import datetime
from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, logout_user
from app.main import main_bp
from app.main.forms import PatientForm
from app.extensions import db
from app.models import (Patient, Examination, ExaminationAnalysis,
                        ExaminationDirection, DoctorDirection, Analysis, User)


def role_required(*roles):
    """Decorator factory for main-section routes.
    If roles is empty — allows any non-admin authenticated user.
    If roles are specified — user must have one of them.
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
                flash('Ваша учётная запись заблокирована. Обратитесь к администратору.', 'danger')
                return redirect(url_for('auth.login'))
            if roles and current_user.role not in roles:
                flash('У вас нет доступа к этому разделу.', 'danger')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


main_required = role_required()
patients_required = role_required('registrar', 'doctor')
examinations_view_required = role_required('registrar', 'doctor', 'cashier', 'analysis_responsible')


# ── Dashboard ─────────────────────────────────────────────────────────────────

@main_bp.route('/')
@main_bp.route('/dashboard')
@main_required
def dashboard():
    stats = None
    if current_user.role in ('registrar', 'doctor'):
        stats = {
            'total': Patient.query.count(),
            'active': Patient.query.filter_by(is_active=True).count(),
            'blocked': Patient.query.filter_by(is_active=False).count(),
        }
    return render_template('main/dashboard.html', stats=stats)


# ── Patients list ─────────────────────────────────────────────────────────────

@main_bp.route('/patients')
@patients_required
def patients_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = Patient.query

    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                Patient.full_name.ilike(like),
                Patient.insurance_number.ilike(like),
                Patient.citizenship.ilike(like),
            )
        )

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'blocked':
        query = query.filter_by(is_active=False)

    patients = query.order_by(Patient.full_name).all()

    return render_template(
        'main/patients/list.html',
        patients=patients,
        search=search,
        status_filter=status_filter,
    )


# ── Create patient ────────────────────────────────────────────────────────────

@main_bp.route('/patients/create', methods=['GET', 'POST'])
@patients_required
def patients_create():
    form = PatientForm()
    if form.validate_on_submit():
        patient = Patient(
            full_name=form.full_name.data.strip(),
            birth_year=form.birth_year.data,
            citizenship=form.citizenship.data.strip(),
            home_address=form.home_address.data.strip(),
            insurance_number=form.insurance_number.data.strip(),
        )
        db.session.add(patient)
        db.session.commit()
        flash(f'Пациент «{patient.full_name}» успешно добавлен.', 'success')
        return redirect(url_for('main.patients_list'))

    return render_template('main/patients/create.html', form=form)


# ── Edit patient ──────────────────────────────────────────────────────────────

@main_bp.route('/patients/<int:patient_id>/edit', methods=['GET', 'POST'])
@patients_required
def patients_edit(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    form = PatientForm(obj=patient, editing_patient=patient)

    if form.validate_on_submit():
        patient.full_name = form.full_name.data.strip()
        patient.birth_year = form.birth_year.data
        patient.citizenship = form.citizenship.data.strip()
        patient.home_address = form.home_address.data.strip()
        patient.insurance_number = form.insurance_number.data.strip()
        db.session.commit()
        flash(f'Данные пациента «{patient.full_name}» обновлены.', 'success')
        return redirect(url_for('main.patients_list'))

    return render_template('main/patients/edit.html', form=form, patient=patient)


# ── Toggle block/unblock patient ──────────────────────────────────────────────

@main_bp.route('/patients/<int:patient_id>/toggle', methods=['POST'])
@patients_required
def patients_toggle(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)

    patient.is_active = not patient.is_active
    db.session.commit()

    action = 'активирован' if patient.is_active else 'деактивирован'
    flash(f'Пациент «{patient.full_name}» {action}.', 'success')
    return redirect(url_for('main.patients_list'))


# ── Examinations helpers ──────────────────────────────────────────────────────

def _exam_form_context():
    """Return data needed to render create/edit examination form."""
    return {
        'patients': Patient.query.filter_by(is_active=True).order_by(Patient.full_name).all(),
        'analyses': Analysis.query.filter_by(is_active=True).order_by(Analysis.name).all(),
        'directions': DoctorDirection.query.filter_by(is_active=True).order_by(DoctorDirection.name).all(),
        'doctors': User.query.filter_by(role='doctor', is_active=True).order_by(User.full_name).all(),
    }


def _parse_exam_form():
    """Parse and validate POST data for examination form. Returns (data_dict, errors)."""
    patient_id = request.form.get('patient_id', type=int)
    analysis_ids = request.form.getlist('analysis_ids', type=int)
    direction_id = request.form.get('direction_id', type=int)
    direction_ids = [direction_id] if direction_id else []

    errors = []

    if not patient_id:
        errors.append('Выберите пациента.')
    else:
        p = db.session.get(Patient, patient_id)
        if not p or not p.is_active:
            errors.append('Выбранный пациент не найден или заблокирован.')

    if not analysis_ids and not direction_ids:
        errors.append('Выберите хотя бы один анализ или направление.')

    doctor_for = {}
    if direction_id:
        doc_id = request.form.get(f'doctor_for_{direction_id}', type=int)
        if not doc_id:
            dir_obj = db.session.get(DoctorDirection, direction_id)
            dir_name = dir_obj.name if dir_obj else f'#{direction_id}'
            errors.append(f'Для направления «{dir_name}» не выбран врач.')
        else:
            doctor_for[direction_id] = doc_id

    data = {
        'patient_id': patient_id,
        'analysis_ids': analysis_ids,
        'direction_ids': direction_ids,
        'doctor_for': doctor_for,
        'selected_patient_id': patient_id,
        'selected_analysis_ids': set(analysis_ids),
        'selected_direction_ids': set(direction_ids),
    }
    return data, errors


# ── Examinations list ─────────────────────────────────────────────────────────

@main_bp.route('/examinations')
@examinations_view_required
def examinations_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    paid_filter = request.args.get('paid', '').strip()

    query = Examination.query.join(Patient, Examination.patient_id == Patient.id)

    if current_user.role == 'doctor':
        query = (query
                 .join(ExaminationDirection, ExaminationDirection.examination_id == Examination.id)
                 .filter(ExaminationDirection.doctor_id == current_user.id)
                 .distinct())
    elif current_user.role == 'analysis_responsible':
        query = (query
                 .join(ExaminationAnalysis, ExaminationAnalysis.examination_id == Examination.id)
                 .join(Analysis, Analysis.id == ExaminationAnalysis.analysis_id)
                 .filter(Analysis.responsible_id == current_user.id)
                 .distinct())

    if search:
        like = f'%{search}%'
        query = query.filter(Patient.full_name.ilike(like))

    if status_filter == 'open':
        query = query.filter(Examination.status == 'open')
    elif status_filter == 'closed':
        query = query.filter(Examination.status == 'closed')

    if paid_filter == 'paid':
        query = query.filter(Examination.is_paid == True)
    elif paid_filter == 'unpaid':
        query = query.filter(Examination.is_paid == False)

    examinations = query.order_by(Examination.created_at.desc()).all()

    return render_template(
        'main/examinations/list.html',
        examinations=examinations,
        search=search,
        status_filter=status_filter,
        paid_filter=paid_filter,
    )


# ── Create examination ────────────────────────────────────────────────────────

@main_bp.route('/examinations/create', methods=['GET', 'POST'])
@patients_required
def examinations_create():
    ctx = _exam_form_context()

    if request.method == 'POST':
        data, errors = _parse_exam_form()
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('main/examinations/create.html', **ctx, **data)

        exam = Examination(patient_id=data['patient_id'], created_by_id=current_user.id)
        db.session.add(exam)
        db.session.flush()

        for aid in data['analysis_ids']:
            db.session.add(ExaminationAnalysis(examination_id=exam.id, analysis_id=aid))
        for did in data['direction_ids']:
            db.session.add(ExaminationDirection(
                examination_id=exam.id,
                direction_id=did,
                doctor_id=data['doctor_for'][did],
            ))

        db.session.commit()
        flash(f'Обследование №{exam.id} успешно создано.', 'success')
        return redirect(url_for('main.examinations_list'))

    defaults = {
        'selected_patient_id': None,
        'selected_analysis_ids': set(),
        'selected_direction_ids': set(),
        'doctor_for': {},
    }
    return render_template('main/examinations/create.html', **ctx, **defaults)


# ── Examination detail ────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>')
@examinations_view_required
def examinations_detail(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)

    if current_user.role == 'doctor':
        assigned_exam_ids = {
            ed.examination_id
            for ed in ExaminationDirection.query.filter_by(doctor_id=current_user.id).all()
        }
        if exam.id not in assigned_exam_ids:
            flash('У вас нет доступа к этому обследованию.', 'danger')
            return redirect(url_for('main.examinations_list'))

    my_analysis_ids = set()
    if current_user.role == 'analysis_responsible':
        my_analysis_ids = {
            a.id for a in Analysis.query.filter_by(responsible_id=current_user.id).all()
        }
        exam_analysis_ids = {ea.analysis_id for ea in exam.exam_analyses}
        if not my_analysis_ids & exam_analysis_ids:
            flash('У вас нет доступа к этому обследованию.', 'danger')
            return redirect(url_for('main.examinations_list'))

    return render_template('main/examinations/detail.html', exam=exam, my_analysis_ids=my_analysis_ids)


# ── Examination report ────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/report')
@examinations_view_required
def examinations_report(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)
    return render_template('main/examinations/report.html', exam=exam)


# ── Edit examination ──────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/edit', methods=['GET', 'POST'])
@patients_required
def examinations_edit(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)

    if not exam.is_open:
        flash('Редактировать можно только открытые обследования.', 'warning')
        return redirect(url_for('main.examinations_list'))

    if exam.is_paid:
        flash('Редактирование невозможно — обследование уже оплачено.', 'warning')
        return redirect(url_for('main.examinations_list'))

    if exam.created_by_id != current_user.id:
        flash('Редактировать обследование может только тот, кто его создал.', 'danger')
        return redirect(url_for('main.examinations_list'))

    ctx = _exam_form_context()

    if request.method == 'POST':
        data, errors = _parse_exam_form()
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('main/examinations/edit.html', exam=exam, **ctx, **data)

        exam.patient_id = data['patient_id']

        for ea in list(exam.exam_analyses):
            db.session.delete(ea)
        for aid in data['analysis_ids']:
            db.session.add(ExaminationAnalysis(examination_id=exam.id, analysis_id=aid))

        for ed in list(exam.exam_directions):
            db.session.delete(ed)
        for did in data['direction_ids']:
            db.session.add(ExaminationDirection(
                examination_id=exam.id,
                direction_id=did,
                doctor_id=data['doctor_for'][did],
            ))

        db.session.commit()
        flash(f'Обследование №{exam.id} обновлено.', 'success')
        return redirect(url_for('main.examinations_list'))

    pre = {
        'selected_patient_id': exam.patient_id,
        'selected_analysis_ids': {ea.analysis_id for ea in exam.exam_analyses},
        'selected_direction_ids': {ed.direction_id for ed in exam.exam_directions},
        'doctor_for': {ed.direction_id: ed.doctor_id for ed in exam.exam_directions},
    }
    return render_template('main/examinations/edit.html', exam=exam, **ctx, **pre)


# ── Close examination ─────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/close', methods=['POST'])
@patients_required
def examinations_close(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)

    if exam.created_by_id != current_user.id:
        flash('Закрыть обследование может только тот, кто его создал.', 'danger')
        return redirect(url_for('main.examinations_list'))

    if not exam.is_open:
        flash('Обследование уже закрыто.', 'warning')
        return redirect(url_for('main.examinations_list'))

    exam.status = Examination.STATUS_CLOSED
    exam.closed_at = datetime.utcnow()
    db.session.commit()
    flash(f'Обследование №{exam.id} закрыто.', 'success')
    return redirect(url_for('main.examinations_list'))


# ── Mark examination as paid ──────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/pay', methods=['POST'])
@role_required('cashier')
def examinations_pay(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)

    if exam.is_paid:
        flash('Обследование уже оплачено.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    exam.is_paid = True
    exam.paid_at = datetime.utcnow()
    exam.paid_by_id = current_user.id
    db.session.commit()
    flash(f'Обследование №{exam.id} отмечено как оплаченное.', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))


# ── Mark analysis as submitted ────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/analyses/<int:ea_id>/submit', methods=['POST'])
@role_required('analysis_responsible')
def examinations_submit_analysis(exam_id, ea_id):
    ea = db.session.get(ExaminationAnalysis, ea_id)
    if ea is None or ea.examination_id != exam_id:
        abort(404)

    if ea.analysis.responsible_id != current_user.id:
        flash('Вы не являетесь ответственным за этот анализ.', 'danger')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if not ea.examination.is_paid:
        flash('Нельзя отметить сдачу анализа — обследование ещё не оплачено.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if ea.is_submitted:
        flash('Анализ уже отмечен как сданный.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    ea.is_submitted = True
    ea.submitted_at = datetime.utcnow()
    ea.submitted_by_id = current_user.id
    db.session.commit()
    flash(f'Анализ «{ea.analysis.name}» отмечен как сданный.', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))


# ── Mark patient visit for direction ─────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/directions/<int:ed_id>/visit', methods=['POST'])
@role_required('doctor')
def examinations_mark_visited(exam_id, ed_id):
    ed = db.session.get(ExaminationDirection, ed_id)
    if ed is None or ed.examination_id != exam_id:
        abort(404)

    if ed.doctor_id != current_user.id:
        flash('Вы не назначены врачом по этому направлению.', 'danger')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if not ed.examination.is_paid:
        flash('Нельзя отметить приход — обследование ещё не оплачено.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if ed.is_visited:
        flash('Приход пациента по этому направлению уже отмечен.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    ed.is_visited = True
    ed.visited_at = datetime.utcnow()
    db.session.commit()
    flash(f'Приход пациента по направлению «{ed.direction.name}» отмечен.', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))
