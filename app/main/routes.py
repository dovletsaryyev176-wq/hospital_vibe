from datetime import datetime
from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import current_user, logout_user
from sqlalchemy.orm import joinedload, subqueryload
from app.main import main_bp
from app.main.forms import PatientForm
from app.extensions import db
from app.models import (Patient, Examination, ExaminationAnalysis,
                        ExaminationDirection, ExaminationAnalysisTool,
                        DoctorDirection, Analysis, AnalysisTool,
                        CombinedAnalysis, User)


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
                flash('Siziň ulanyjyňyz bloklanan.', 'danger')
                return redirect(url_for('auth.login'))
            if roles and current_user.role not in roles:
                flash('Siz bu bölege girip bilmeýärsiňiz.', 'danger')
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
                Patient.passport_number.ilike(like),
                Patient.insurance_number.ilike(like),
                Patient.citizenship.ilike(like),
            )
        )

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'blocked':
        query = query.filter_by(is_active=False)

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(Patient.full_name).paginate(page=page, per_page=15, error_out=False)

    return render_template(
        'main/patients/list.html',
        patients=pagination.items,
        pagination=pagination,
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
            passport_number=form.passport_number.data.strip() or None,
            insurance_number=form.insurance_number.data.strip() or None,
        )
        db.session.add(patient)
        db.session.commit()
        flash(f'Syrkaw «{patient.full_name}» döredilen.', 'success')
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
        patient.passport_number = form.passport_number.data.strip() or None
        patient.insurance_number = form.insurance_number.data.strip() or None
        db.session.commit()
        flash(f'Syrkaw «{patient.full_name}» maglumatlary täzelenen.', 'success')
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

    action = 'aktiw' if patient.is_active else 'bloklanan'
    flash(f'Syrkaw «{patient.full_name}» {action}.', 'success')
    return redirect(url_for('main.patients_list'))


# ── Patient examination history ───────────────────────────────────────────────

@main_bp.route('/patients/<int:patient_id>/history')
@patients_required
def patients_history(patient_id):
    patient = db.session.get(Patient, patient_id)
    if patient is None:
        abort(404)
    examinations = (
        Examination.query
        .filter_by(patient_id=patient_id)
        .options(
            subqueryload(Examination.exam_analyses).joinedload(ExaminationAnalysis.analysis),
            subqueryload(Examination.exam_directions).joinedload(ExaminationDirection.direction),
            subqueryload(Examination.exam_directions).joinedload(ExaminationDirection.doctor),
            subqueryload(Examination.exam_tools).joinedload(ExaminationAnalysisTool.tool),
            joinedload(Examination.created_by),
            joinedload(Examination.paid_by),
        )
        .order_by(Examination.created_at.desc())
        .all()
    )
    return render_template('main/patients/history.html',
                           patient=patient, examinations=examinations)


# ── Patients search API ───────────────────────────────────────────────────────

@main_bp.route('/patients/search')
@patients_required
def patients_search():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])
    patients = (Patient.query
                .filter(Patient.is_active == True,
                        Patient.full_name.ilike(f'%{q}%'))
                .order_by(Patient.full_name)
                .limit(20)
                .all())
    return jsonify([{
        'id': p.id,
        'full_name': p.full_name,
        'birth_year': p.birth_year,
        'passport_number': p.passport_number or '',
        'insurance_number': p.insurance_number or '',
    } for p in patients])


# ── Examinations helpers ──────────────────────────────────────────────────────

def _exam_form_context():
    """Return data needed to render create/edit examination form."""
    all_tools = (AnalysisTool.query
                 .filter_by(is_active=True)
                 .options(joinedload(AnalysisTool.analysis))
                 .order_by(AnalysisTool.name)
                 .all())
    analysis_tools_map = {}
    for t in all_tools:
        analysis_tools_map.setdefault(t.analysis_id, []).append(t.id)
    return {
        'analyses': Analysis.query.filter_by(is_active=True).order_by(Analysis.name).all(),
        'combined_analyses': CombinedAnalysis.query.filter_by(is_active=True).options(joinedload(CombinedAnalysis.analyses)).order_by(CombinedAnalysis.name).all(),
        'directions': DoctorDirection.query.filter_by(is_active=True).order_by(DoctorDirection.name).all(),
        'doctors': User.query.filter(
            User.role.in_(['doctor', 'analysis_responsible']),
            User.is_active == True,
        ).options(joinedload(User.directions)).order_by(User.full_name).all(),
        'all_tools': all_tools,
        'analysis_tools_map': analysis_tools_map,
    }


def _parse_exam_form():
    """Parse and validate POST data for examination form. Returns (data_dict, errors)."""
    patient_id = request.form.get('patient_id', type=int)
    analysis_ids = list(dict.fromkeys(request.form.getlist('analysis_ids', type=int)))
    direction_ids = request.form.getlist('direction_ids', type=int)
    tool_ids = list(dict.fromkeys(request.form.getlist('tool_ids', type=int)))

    errors = []

    if not patient_id:
        errors.append('Syrkawy saýlaň.')
    else:
        p = db.session.get(Patient, patient_id)
        if not p or not p.is_active:
            errors.append('Saýlanan syrkaw tapylmady ýa-da bloklanan.')

    if not analysis_ids and not direction_ids:
        errors.append('Iň bolmanda 1 analiz ýa-da ugur kesgitläň.')

    doctor_for = {}
    if direction_ids:
        directions_by_id = {d.id: d for d in DoctorDirection.query.filter(DoctorDirection.id.in_(direction_ids)).all()}
    else:
        directions_by_id = {}
    for did in direction_ids:
        doc_id = request.form.get(f'doctor_for_{did}', type=int)
        if not doc_id:
            dir_obj = directions_by_id.get(did)
            dir_name = dir_obj.name if dir_obj else f'#{did}'
            errors.append(f'Ugur «{dir_name}» üçin lukman bellenmedik.')
        else:
            doctor_for[did] = doc_id

    data = {
        'patient_id': patient_id,
        'analysis_ids': analysis_ids,
        'direction_ids': direction_ids,
        'tool_ids': tool_ids,
        'doctor_for': doctor_for,
        'selected_patient_id': patient_id,
        'selected_analysis_ids': set(analysis_ids),
        'selected_direction_ids': set(direction_ids),
        'selected_tool_ids': set(tool_ids),
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
        query = query.filter(Examination.status == Examination.STATUS_OPEN)
    elif status_filter == 'closed':
        query = query.filter(Examination.status == Examination.STATUS_CLOSED)

    if paid_filter == 'paid':
        query = query.filter(Examination.is_paid == True)
    elif paid_filter == 'unpaid':
        query = query.filter(Examination.is_paid == False)

    page = request.args.get('page', 1, type=int)
    pagination = (query
        .options(
            joinedload(Examination.patient),
            joinedload(Examination.created_by),
            subqueryload(Examination.exam_analyses),
            subqueryload(Examination.exam_directions),
        )
        .order_by(Examination.created_at.desc())
        .paginate(page=page, per_page=15, error_out=False))

    return render_template(
        'main/examinations/list.html',
        examinations=pagination.items,
        pagination=pagination,
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
            selected_patient = db.session.get(Patient, data['patient_id']) if data['patient_id'] else None
            return render_template('main/examinations/create.html', **ctx, **data,
                                   selected_patient=selected_patient)

        patient = db.session.get(Patient, data['patient_id'])
        exam = Examination(
            patient_id=data['patient_id'],
            created_by_id=current_user.id,
            patient_has_insurance=bool(patient.insurance_number),
        )
        db.session.add(exam)
        db.session.flush()

        analyses_by_id = {a.id: a for a in Analysis.query.filter(
            Analysis.id.in_(data['analysis_ids'])).all()} if data['analysis_ids'] else {}
        for aid in data['analysis_ids']:
            a = analyses_by_id[aid]
            db.session.add(ExaminationAnalysis(
                examination_id=exam.id,
                analysis_id=aid,
                price=a.price,
                is_insurance=a.is_insurance,
            ))
        directions_by_id = {d.id: d for d in DoctorDirection.query.filter(
            DoctorDirection.id.in_(data['direction_ids'])).all()} if data['direction_ids'] else {}
        for did in data['direction_ids']:
            d = directions_by_id[did]
            db.session.add(ExaminationDirection(
                examination_id=exam.id,
                direction_id=did,
                doctor_id=data['doctor_for'][did],
                price=d.price,
                is_insurance=d.is_insurance,
            ))
        tools_by_id = {t.id: t for t in AnalysisTool.query.filter(
            AnalysisTool.id.in_(data['tool_ids'])).all()} if data['tool_ids'] else {}
        for tid in data['tool_ids']:
            t = tools_by_id[tid]
            db.session.add(ExaminationAnalysisTool(
                examination_id=exam.id,
                tool_id=tid,
                price=t.total_price,
                is_insurance=t.is_insurance,
            ))

        db.session.commit()
        flash(f'Barlag №{exam.id} döredilen.', 'success')
        return redirect(url_for('main.examinations_list'))

    defaults = {
        'selected_patient_id': None,
        'selected_patient': None,
        'selected_analysis_ids': set(),
        'selected_direction_ids': set(),
        'selected_tool_ids': set(),
        'doctor_for': {},
    }
    return render_template('main/examinations/create.html', **ctx, **defaults)


# ── Examination detail ────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>')
@examinations_view_required
def examinations_detail(exam_id):
    exam = (
        Examination.query
        .filter_by(id=exam_id)
        .options(
            joinedload(Examination.patient),
            joinedload(Examination.created_by),
            joinedload(Examination.paid_by),
            subqueryload(Examination.exam_analyses).joinedload(ExaminationAnalysis.analysis),
            subqueryload(Examination.exam_directions).joinedload(ExaminationDirection.direction),
            subqueryload(Examination.exam_directions).joinedload(ExaminationDirection.doctor),
            subqueryload(Examination.exam_tools).joinedload(ExaminationAnalysisTool.tool).joinedload(AnalysisTool.analysis),
        )
        .first()
    )
    if exam is None:
        abort(404)

    if current_user.role == 'doctor':
        if not ExaminationDirection.query.filter_by(
            doctor_id=current_user.id, examination_id=exam_id
        ).first():
            flash('Siz üçin bu barlag gadagan.', 'danger')
            return redirect(url_for('main.examinations_list'))

    my_analysis_ids = set()
    if current_user.role == 'analysis_responsible':
        exam_analysis_ids = {ea.analysis_id for ea in exam.exam_analyses}
        my_analysis_ids = {
            a.id for a in Analysis.query.filter(
                Analysis.responsible_id == current_user.id,
                Analysis.id.in_(exam_analysis_ids),
            ).all()
        }
        if not my_analysis_ids:
            flash('Siz üçin bu barlag gadagan.', 'danger')
            return redirect(url_for('main.examinations_list'))

    return render_template('main/examinations/detail.html', exam=exam, my_analysis_ids=my_analysis_ids)


# ── Examination report ────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/report')
@examinations_view_required
def examinations_report(exam_id):
    exam = (
        Examination.query
        .filter_by(id=exam_id)
        .options(
            joinedload(Examination.patient),
            joinedload(Examination.created_by),
            subqueryload(Examination.exam_analyses).joinedload(ExaminationAnalysis.analysis),
            subqueryload(Examination.exam_directions).joinedload(ExaminationDirection.direction),
            subqueryload(Examination.exam_directions).joinedload(ExaminationDirection.doctor),
            subqueryload(Examination.exam_tools).joinedload(ExaminationAnalysisTool.tool),
        )
        .first()
    )
    if exam is None:
        abort(404)

    if current_user.role == 'doctor':
        if not ExaminationDirection.query.filter_by(
            doctor_id=current_user.id, examination_id=exam_id
        ).first():
            abort(403)

    if current_user.role == 'analysis_responsible':
        exam_analysis_ids = {ea.analysis_id for ea in exam.exam_analyses}
        has_own = Analysis.query.filter(
            Analysis.responsible_id == current_user.id,
            Analysis.id.in_(exam_analysis_ids),
        ).first()
        if not has_own:
            abort(403)

    return render_template('main/examinations/report.html', exam=exam)


# ── Edit examination ──────────────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/edit', methods=['GET', 'POST'])
@patients_required
def examinations_edit(exam_id):
    exam = (
        Examination.query
        .filter_by(id=exam_id)
        .options(
            joinedload(Examination.patient),
            subqueryload(Examination.exam_analyses),
            subqueryload(Examination.exam_directions),
            subqueryload(Examination.exam_tools),
        )
        .first()
    )
    if exam is None:
        abort(404)

    if not exam.is_open:
        flash('Diňe açyk barlaglary üýtgedip bolýar.', 'warning')
        return redirect(url_for('main.examinations_list'))

    if exam.is_paid:
        flash('Üýtgetmek mümkin däl-barlag tölenen.', 'warning')
        return redirect(url_for('main.examinations_list'))

    if exam.created_by_id != current_user.id and current_user.role != 'registrar':
        flash('Diňe barlagy döreden üýtgedip bilýär.', 'danger')
        return redirect(url_for('main.examinations_list'))

    ctx = _exam_form_context()

    if request.method == 'POST':
        data, errors = _parse_exam_form()
        if errors:
            for e in errors:
                flash(e, 'danger')
            selected_patient = db.session.get(Patient, data['patient_id']) if data['patient_id'] else None
            return render_template('main/examinations/edit.html', exam=exam, **ctx, **data,
                                   selected_patient=selected_patient)

        patient = db.session.get(Patient, data['patient_id'])
        exam.patient_id = data['patient_id']
        exam.patient_has_insurance = bool(patient.insurance_number)

        for ea in list(exam.exam_analyses):
            db.session.delete(ea)
        analyses_by_id = {a.id: a for a in Analysis.query.filter(
            Analysis.id.in_(data['analysis_ids'])).all()} if data['analysis_ids'] else {}
        for aid in data['analysis_ids']:
            a = analyses_by_id[aid]
            db.session.add(ExaminationAnalysis(
                examination_id=exam.id,
                analysis_id=aid,
                price=a.price,
                is_insurance=a.is_insurance,
            ))

        for ed in list(exam.exam_directions):
            db.session.delete(ed)
        directions_by_id = {d.id: d for d in DoctorDirection.query.filter(
            DoctorDirection.id.in_(data['direction_ids'])).all()} if data['direction_ids'] else {}
        for did in data['direction_ids']:
            d = directions_by_id[did]
            db.session.add(ExaminationDirection(
                examination_id=exam.id,
                direction_id=did,
                doctor_id=data['doctor_for'][did],
                price=d.price,
                is_insurance=d.is_insurance,
            ))

        for et in list(exam.exam_tools):
            db.session.delete(et)
        tools_by_id = {t.id: t for t in AnalysisTool.query.filter(
            AnalysisTool.id.in_(data['tool_ids'])).all()} if data['tool_ids'] else {}
        for tid in data['tool_ids']:
            t = tools_by_id[tid]
            db.session.add(ExaminationAnalysisTool(
                examination_id=exam.id,
                tool_id=tid,
                price=t.total_price,
                is_insurance=t.is_insurance,
            ))

        db.session.commit()
        flash(f'Barlag №{exam.id} maglumatlary täzelenen.', 'success')
        return redirect(url_for('main.examinations_list'))

    pre = {
        'selected_patient_id': exam.patient_id,
        'selected_patient': exam.patient,
        'selected_analysis_ids': {ea.analysis_id for ea in exam.exam_analyses},
        'selected_direction_ids': {ed.direction_id for ed in exam.exam_directions},
        'selected_tool_ids': {et.tool_id for et in exam.exam_tools},
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

    if exam.created_by_id != current_user.id and current_user.role != 'registrar':
        flash('Diňe döreden barlagy ýapyp bilýär.', 'danger')
        return redirect(url_for('main.examinations_list'))

    if not exam.is_open:
        flash('Barlag eýýäm ýapylan.', 'warning')
        return redirect(url_for('main.examinations_list'))

    exam.status = Examination.STATUS_CLOSED
    exam.closed_at = datetime.now()
    db.session.commit()
    flash(f'Barlag №{exam.id} ýapylan.', 'success')
    return redirect(url_for('main.examinations_list'))


# ── Toggle insurance discount ─────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/toggle-insurance', methods=['POST'])
@role_required('cashier')
def examinations_toggle_insurance(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)

    if exam.is_paid:
        flash('Tölenen barlagyň ätiýaçlandyryşyny üýtgedip bolmaýar.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    exam.patient_has_insurance = not exam.patient_has_insurance
    db.session.commit()

    state = 'işjeňleşdirildi' if exam.patient_has_insurance else 'öçürildi'
    flash(f'Ätiýaçlandyryş arzanladyşy {state}.', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))


# ── Mark examination as paid ──────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/pay', methods=['POST'])
@role_required('cashier')
def examinations_pay(exam_id):
    exam = db.session.get(Examination, exam_id)
    if exam is None:
        abort(404)

    if exam.is_paid:
        flash('Barlag eýýäm tölenen.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    exam.is_paid = True
    exam.paid_at = datetime.now()
    exam.paid_by_id = current_user.id
    db.session.commit()
    flash(f'Barlag №{exam.id} tölenen diýip bellenilen.', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))


# ── Mark analysis as submitted ────────────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/analyses/<int:ea_id>/submit', methods=['POST'])
@role_required('analysis_responsible')
def examinations_submit_analysis(exam_id, ea_id):
    ea = (
        ExaminationAnalysis.query
        .filter_by(id=ea_id)
        .options(
            joinedload(ExaminationAnalysis.analysis),
            joinedload(ExaminationAnalysis.examination),
        )
        .first()
    )
    if ea is None or ea.examination_id != exam_id:
        abort(404)

    if ea.analysis.responsible_id != current_user.id:
        flash('Bu analiziň jogapkäri Siz däl.', 'danger')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if not ea.examination.is_paid:
        flash('Tölenmedik analize bellik goýup bolmaýar.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if ea.is_submitted:
        flash('Analiz geçilen diýip bellenilen.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    ea.is_submitted = True
    ea.submitted_at = datetime.now()
    ea.submitted_by_id = current_user.id
    db.session.commit()
    flash(f'Analiz «{ea.analysis.name}» geçilen diýip bellenilen.', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))


# ── Mark patient visit for direction ─────────────────────────────────────────

@main_bp.route('/examinations/<int:exam_id>/directions/<int:ed_id>/visit', methods=['POST'])
@role_required('doctor')
def examinations_mark_visited(exam_id, ed_id):
    ed = (
        ExaminationDirection.query
        .filter_by(id=ed_id)
        .options(
            joinedload(ExaminationDirection.examination),
            joinedload(ExaminationDirection.direction),
        )
        .first()
    )
    if ed is None or ed.examination_id != exam_id:
        abort(404)

    if ed.doctor_id != current_user.id:
        flash('Siz bu ugur boýunça lukman däl.', 'danger')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if not ed.examination.is_paid:
        flash('Gelenini belläp bolmaýar-tölenmedik.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    if ed.is_visited:
        flash('Bu ugur boýunça geçilen diýilip bellenilen.', 'warning')
        return redirect(url_for('main.examinations_detail', exam_id=exam_id))

    ed.is_visited = True
    ed.visited_at = datetime.now()
    db.session.commit()
    flash(f'Syrkaw bu ugur geçilen diýip bellenilen «{ed.direction.name}» .', 'success')
    return redirect(url_for('main.examinations_detail', exam_id=exam_id))
