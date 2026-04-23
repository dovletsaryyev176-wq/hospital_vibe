from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, logout_user
from app.main import main_bp
from app.main.forms import PatientForm
from app.extensions import db
from app.models import Patient


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
