from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.forms import UserForm, AnalysisForm, DirectionForm, CombinedAnalysisForm
from app.extensions import db
from app.models import User, Analysis, DoctorDirection, CombinedAnalysis, Examination


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.admin_login'))
        if not current_user.is_administrator() or not current_user.is_active:
            flash('Girmek gadagan.', 'danger')
            return redirect(url_for('auth.admin_login'))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    total = User.query.count()
    active = User.query.filter_by(is_active=True).count()
    blocked = User.query.filter_by(is_active=False).count()
    counts = dict(
        db.session.query(User.role, func.count(User.id)).group_by(User.role).all()
    )
    by_role = {role: counts.get(role, 0) for role in User.ROLES}
    return render_template(
        'admin/dashboard.html',
        total=total,
        active=active,
        blocked=blocked,
        by_role=by_role,
        role_labels=User.ROLES,
    )


# ── Users list ───────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@admin_required
def users_list():
    search = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '').strip()

    query = User.query

    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                User.full_name.ilike(like),
                User.username.ilike(like),
                User.phone_number.ilike(like),
            )
        )

    if role_filter and role_filter in User.ROLES:
        query = query.filter_by(role=role_filter)

    users = query.options(joinedload(User.directions)).order_by(User.full_name).all()

    return render_template(
        'admin/users/list.html',
        users=users,
        search=search,
        role_filter=role_filter,
        roles=User.ROLES,
    )


# ── Create user ──────────────────────────────────────────────────────────────

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def users_create():
    form = UserForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data.strip(),
            full_name=form.full_name.data.strip(),
            role=form.role.data,
            phone_number=form.phone_number.data.strip(),
            cabinet=form.cabinet.data.strip() or None,
        )
        user.set_password(form.password.data)
        selected_ids = form.direction_ids.data or []
        if selected_ids:
            user.directions = DoctorDirection.query.filter(DoctorDirection.id.in_(selected_ids)).all()
        db.session.add(user)
        db.session.commit()
        flash(f'Ulanyjy «{user.full_name}» döredilen.', 'success')
        return redirect(url_for('admin.users_list'))

    return render_template('admin/users/create.html', form=form)


# ── Edit user ────────────────────────────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def users_edit(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    form = UserForm(obj=user, editing_user=user)

    if request.method == 'GET':
        form.direction_ids.data = [d.id for d in user.directions]

    if form.validate_on_submit():
        user.full_name = form.full_name.data.strip()
        user.username = form.username.data.strip()
        user.role = form.role.data
        user.phone_number = form.phone_number.data.strip()
        user.cabinet = form.cabinet.data.strip() or None

        selected_ids = form.direction_ids.data or []
        user.directions = DoctorDirection.query.filter(DoctorDirection.id.in_(selected_ids)).all() if selected_ids else []

        if form.password.data:
            user.set_password(form.password.data)

        db.session.commit()
        flash(f'Ulanyjy «{user.full_name}» maglumatlary täzelendi.', 'success')
        return redirect(url_for('admin.users_list'))

    return render_template('admin/users/edit.html', form=form, user=user)


# ── Toggle block/unblock ─────────────────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def users_toggle(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    if user.id == current_user.id:
        flash('Öz ulanyjyňy bloklap bolmaýar.', 'warning')
        return redirect(url_for('admin.users_list'))

    user.is_active = not user.is_active
    db.session.commit()

    action = 'aktiw' if user.is_active else 'bloklanan'
    flash(f'Ulanyjy «{user.full_name}» {action}.', 'success')
    return redirect(url_for('admin.users_list'))


# ── Analyses list ─────────────────────────────────────────────────────────────

@admin_bp.route('/analyses')
@admin_required
def analyses_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = Analysis.query.join(Analysis.responsible)

    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                Analysis.name.ilike(like),
                User.full_name.ilike(like),
            )
        )

    if status_filter == 'active':
        query = query.filter(Analysis.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(Analysis.is_active == False)

    analyses = query.options(joinedload(Analysis.responsible)).order_by(Analysis.name).all()

    return render_template(
        'admin/analyses/list.html',
        analyses=analyses,
        search=search,
        status_filter=status_filter,
    )


# ── Create analysis ───────────────────────────────────────────────────────────

@admin_bp.route('/analyses/create', methods=['GET', 'POST'])
@admin_required
def analyses_create():
    form = AnalysisForm()
    if form.validate_on_submit():
        analysis = Analysis(
            name=form.name.data.strip(),
            price=form.price.data,
            responsible_id=form.responsible_id.data,
            is_insurance=form.is_insurance.data,
        )
        db.session.add(analysis)
        db.session.commit()
        flash(f'Analiz «{analysis.name}» döredilen.', 'success')
        return redirect(url_for('admin.analyses_list'))

    return render_template('admin/analyses/create.html', form=form)


# ── Edit analysis ─────────────────────────────────────────────────────────────

@admin_bp.route('/analyses/<int:analysis_id>/edit', methods=['GET', 'POST'])
@admin_required
def analyses_edit(analysis_id):
    analysis = db.session.get(Analysis, analysis_id)
    if analysis is None:
        abort(404)

    form = AnalysisForm(obj=analysis, editing_analysis=analysis)

    if form.validate_on_submit():
        analysis.name = form.name.data.strip()
        analysis.price = form.price.data
        analysis.responsible_id = form.responsible_id.data
        analysis.is_insurance = form.is_insurance.data
        db.session.commit()
        flash(f'Analiz «{analysis.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.analyses_list'))

    return render_template('admin/analyses/edit.html', form=form, analysis=analysis)


# ── Toggle analysis ───────────────────────────────────────────────────────────

@admin_bp.route('/analyses/<int:analysis_id>/toggle', methods=['POST'])
@admin_required
def analyses_toggle(analysis_id):
    analysis = db.session.get(Analysis, analysis_id)
    if analysis is None:
        abort(404)

    analysis.is_active = not analysis.is_active
    db.session.commit()

    action = 'aktiw' if analysis.is_active else 'bloklanan'
    flash(f'Analiz «{analysis.name}» {action}.', 'success')
    return redirect(url_for('admin.analyses_list'))


# ── Directions list ───────────────────────────────────────────────────────────

@admin_bp.route('/directions')
@admin_required
def directions_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = DoctorDirection.query

    if search:
        query = query.filter(DoctorDirection.name.ilike(f'%{search}%'))

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'blocked':
        query = query.filter_by(is_active=False)

    directions = query.order_by(DoctorDirection.name).all()

    return render_template(
        'admin/directions/list.html',
        directions=directions,
        search=search,
        status_filter=status_filter,
    )


# ── Create direction ──────────────────────────────────────────────────────────

@admin_bp.route('/directions/create', methods=['GET', 'POST'])
@admin_required
def directions_create():
    form = DirectionForm()
    if form.validate_on_submit():
        direction = DoctorDirection(name=form.name.data.strip(), price=form.price.data, is_insurance=form.is_insurance.data)
        db.session.add(direction)
        db.session.commit()
        flash(f'Ugur «{direction.name}» döredilen.', 'success')
        return redirect(url_for('admin.directions_list'))

    return render_template('admin/directions/create.html', form=form)


# ── Edit direction ────────────────────────────────────────────────────────────

@admin_bp.route('/directions/<int:direction_id>/edit', methods=['GET', 'POST'])
@admin_required
def directions_edit(direction_id):
    direction = db.session.get(DoctorDirection, direction_id)
    if direction is None:
        abort(404)

    form = DirectionForm(obj=direction, editing_direction=direction)

    if form.validate_on_submit():
        direction.name = form.name.data.strip()
        direction.price = form.price.data
        direction.is_insurance = form.is_insurance.data
        db.session.commit()
        flash(f'Ugur «{direction.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.directions_list'))

    return render_template('admin/directions/edit.html', form=form, direction=direction)


# ── Toggle direction ──────────────────────────────────────────────────────────

@admin_bp.route('/directions/<int:direction_id>/toggle', methods=['POST'])
@admin_required
def directions_toggle(direction_id):
    direction = db.session.get(DoctorDirection, direction_id)
    if direction is None:
        abort(404)

    direction.is_active = not direction.is_active
    db.session.commit()

    action = 'aktiw' if direction.is_active else 'bloklanan'
    flash(f'Ugur «{direction.name}» {action}.', 'success')
    return redirect(url_for('admin.directions_list'))


# ── Daily report ─────────────────────────────────────────────────────────────

@admin_bp.route('/daily-report')
@admin_required
def daily_report():
    rows = (
        db.session.query(
            func.date(Examination.paid_at).label('day'),
            func.count(Examination.id).label('cnt'),
        )
        .filter(Examination.paid_at.isnot(None))
        .group_by(func.date(Examination.paid_at))
        .order_by(func.date(Examination.paid_at).desc())
        .all()
    )
    return render_template('admin/reports/daily.html', rows=rows)


# ── Combined analyses list ────────────────────────────────────────────────────

@admin_bp.route('/combined-analyses')
@admin_required
def combined_analyses_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = CombinedAnalysis.query

    if search:
        query = query.filter(CombinedAnalysis.name.ilike(f'%{search}%'))

    if status_filter == 'active':
        query = query.filter(CombinedAnalysis.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(CombinedAnalysis.is_active == False)

    combined_analyses = query.options(joinedload(CombinedAnalysis.analyses)).order_by(CombinedAnalysis.name).all()

    return render_template(
        'admin/combined_analyses/list.html',
        combined_analyses=combined_analyses,
        search=search,
        status_filter=status_filter,
    )


# ── Create combined analysis ──────────────────────────────────────────────────

@admin_bp.route('/combined-analyses/create', methods=['GET', 'POST'])
@admin_required
def combined_analyses_create():
    form = CombinedAnalysisForm()
    if form.validate_on_submit():
        combined = CombinedAnalysis(name=form.name.data.strip())
        combined.analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
        db.session.add(combined)
        db.session.commit()
        flash(f'Kombinlenen analiz «{combined.name}» döredilen.', 'success')
        return redirect(url_for('admin.combined_analyses_list'))

    return render_template('admin/combined_analyses/create.html', form=form)


# ── Edit combined analysis ────────────────────────────────────────────────────

@admin_bp.route('/combined-analyses/<int:combined_id>/edit', methods=['GET', 'POST'])
@admin_required
def combined_analyses_edit(combined_id):
    combined = db.session.get(CombinedAnalysis, combined_id)
    if combined is None:
        abort(404)

    form = CombinedAnalysisForm(obj=combined, editing_combined=combined)

    if form.validate_on_submit():
        combined.name = form.name.data.strip()
        combined.analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
        db.session.commit()
        flash(f'Kombinlenen analiz «{combined.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.combined_analyses_list'))

    if request.method == 'GET':
        form.analysis_ids.data = [a.id for a in combined.analyses]

    return render_template('admin/combined_analyses/edit.html', form=form, combined=combined)


# ── Toggle combined analysis ──────────────────────────────────────────────────

@admin_bp.route('/combined-analyses/<int:combined_id>/toggle', methods=['POST'])
@admin_required
def combined_analyses_toggle(combined_id):
    combined = db.session.get(CombinedAnalysis, combined_id)
    if combined is None:
        abort(404)

    combined.is_active = not combined.is_active
    db.session.commit()

    action = 'aktiw' if combined.is_active else 'bloklanan'
    flash(f'Kombinlenen analiz «{combined.name}» {action}.', 'success')
    return redirect(url_for('admin.combined_analyses_list'))
