from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload, contains_eager
from app.admin import admin_bp
from app.admin.forms import (UserForm, AnalysisForm, DirectionForm, DirectionCategoryForm, CombinedAnalysisForm,
                             AnalysisToolForm, BlankForm, AnalysisToolCategoryForm, AnalysisToolSubcategoryForm,
                             DepartmentForm, RoomTypeForm, RoomForm, BedForm, MealForm, MedicineForm,
                             OperationForm)
from app.extensions import db
from app.models import (User, Analysis, DoctorDirection, DoctorDirectionCategory, CombinedAnalysis, Examination,
                        AnalysisTool, Blank, AnalysisToolCategory, AnalysisToolSubcategory,
                        Department, RoomType, Room, Bed, Meal, Medicine, Operation)


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
            # optional — None when the key is missing from the POST altogether
            cabinet=(form.cabinet.data or '').strip() or None,
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
        if user.id == current_user.id and form.role.data != 'administrator':
            flash('Öz roluňyzy üýtgedip bolmaýar.', 'danger')
            return redirect(url_for('admin.users_edit', user_id=user.id))

        user.full_name = form.full_name.data.strip()
        user.username = form.username.data.strip()
        user.role = form.role.data
        user.phone_number = form.phone_number.data.strip()
        user.cabinet = (form.cabinet.data or '').strip() or None

        # Departments belong to the inpatient roles. A role that may not hold
        # them must not keep the ones it had: the user-departments page refuses
        # to touch such a user, so an attachment left behind here becomes
        # invisible and uneditable — and comes back into force the moment the
        # user is moved to an inpatient role again.
        if not user.can_have_departments():
            user.departments = []

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
    cat_filter = request.args.get('cat', 0, type=int)

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

    if cat_filter:
        query = query.filter(Analysis.category_id == cat_filter)

    analyses = (query
                .options(contains_eager(Analysis.responsible), joinedload(Analysis.category))
                .order_by(Analysis.name)
                .all())
    all_categories = DoctorDirectionCategory.query.filter_by(is_active=True).order_by(DoctorDirectionCategory.name).all()

    return render_template(
        'admin/analyses/list.html',
        analyses=analyses,
        search=search,
        status_filter=status_filter,
        cat_filter=cat_filter,
        all_categories=all_categories,
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
            category_id=form.category_id.data or None,
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

    if request.method == 'GET':
        form.category_id.data = analysis.category_id or 0

    if form.validate_on_submit():
        analysis.name = form.name.data.strip()
        analysis.price = form.price.data
        analysis.responsible_id = form.responsible_id.data
        analysis.is_insurance = form.is_insurance.data
        analysis.category_id = form.category_id.data or None
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
    cat_filter = request.args.get('cat', 0, type=int)

    query = DoctorDirection.query

    if search:
        query = query.filter(DoctorDirection.name.ilike(f'%{search}%'))

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'blocked':
        query = query.filter_by(is_active=False)

    if cat_filter:
        query = query.filter(DoctorDirection.category_id == cat_filter)

    directions = query.options(joinedload(DoctorDirection.category)).order_by(DoctorDirection.name).all()
    all_categories = DoctorDirectionCategory.query.filter_by(is_active=True).order_by(DoctorDirectionCategory.name).all()

    return render_template(
        'admin/directions/list.html',
        directions=directions,
        search=search,
        status_filter=status_filter,
        cat_filter=cat_filter,
        all_categories=all_categories,
    )


# ── Create direction ──────────────────────────────────────────────────────────

@admin_bp.route('/directions/create', methods=['GET', 'POST'])
@admin_required
def directions_create():
    form = DirectionForm()
    if form.validate_on_submit():
        direction = DoctorDirection(
            name=form.name.data.strip(),
            price=form.price.data,
            is_insurance=form.is_insurance.data,
            category_id=form.category_id.data or None,
        )
        direction.analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
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

    if request.method == 'GET':
        form.analysis_ids.data = [a.id for a in direction.analyses]
        form.category_id.data = direction.category_id or 0

    if form.validate_on_submit():
        direction.name = form.name.data.strip()
        direction.price = form.price.data
        direction.is_insurance = form.is_insurance.data
        direction.category_id = form.category_id.data or None
        direction.analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
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


# ── Direction categories ──────────────────────────────────────────────────────

@admin_bp.route('/direction-categories')
@admin_required
def direction_categories_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = DoctorDirectionCategory.query
    if search:
        query = query.filter(DoctorDirectionCategory.name.ilike(f'%{search}%'))
    if status_filter == 'active':
        query = query.filter(DoctorDirectionCategory.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(DoctorDirectionCategory.is_active == False)

    categories = query.order_by(DoctorDirectionCategory.name).all()
    dir_counts = dict(
        db.session.query(
            DoctorDirection.category_id,
            func.count(DoctorDirection.id),
        )
        .filter(DoctorDirection.category_id.isnot(None))
        .group_by(DoctorDirection.category_id)
        .all()
    )
    analysis_counts = dict(
        db.session.query(
            Analysis.category_id,
            func.count(Analysis.id),
        )
        .filter(Analysis.category_id.isnot(None))
        .group_by(Analysis.category_id)
        .all()
    )
    blank_counts = dict(
        db.session.query(Blank.category_id, func.count(Blank.id))
        .filter(Blank.category_id.isnot(None))
        .group_by(Blank.category_id)
        .all()
    )
    tool_counts = dict(
        db.session.query(AnalysisTool.direction_category_id, func.count(AnalysisTool.id))
        .filter(AnalysisTool.direction_category_id.isnot(None))
        .group_by(AnalysisTool.direction_category_id)
        .all()
    )
    return render_template(
        'admin/direction_categories/list.html',
        categories=categories,
        dir_counts=dir_counts,
        analysis_counts=analysis_counts,
        blank_counts=blank_counts,
        tool_counts=tool_counts,
        search=search,
        status_filter=status_filter,
    )


@admin_bp.route('/direction-categories/create', methods=['GET', 'POST'])
@admin_required
def direction_categories_create():
    form = DirectionCategoryForm()
    if form.validate_on_submit():
        cat = DoctorDirectionCategory(name=form.name.data.strip())
        db.session.add(cat)
        db.session.commit()
        flash(f'Kategoriýa «{cat.name}» döredilen.', 'success')
        return redirect(url_for('admin.direction_categories_list'))
    return render_template('admin/direction_categories/create.html', form=form)


@admin_bp.route('/direction-categories/<int:cat_id>/edit', methods=['GET', 'POST'])
@admin_required
def direction_categories_edit(cat_id):
    cat = db.session.get(DoctorDirectionCategory, cat_id)
    if cat is None:
        abort(404)
    form = DirectionCategoryForm(editing_category=cat)
    if not form.is_submitted():
        form.name.data = cat.name
    if form.validate_on_submit():
        cat.name = form.name.data.strip()
        db.session.commit()
        flash(f'Kategoriýa «{cat.name}» täzelenen.', 'success')
        return redirect(url_for('admin.direction_categories_list'))
    return render_template('admin/direction_categories/edit.html', form=form, cat=cat)


@admin_bp.route('/direction-categories/<int:cat_id>/toggle', methods=['POST'])
@admin_required
def direction_categories_toggle(cat_id):
    cat = db.session.get(DoctorDirectionCategory, cat_id)
    if cat is None:
        abort(404)
    cat.is_active = not cat.is_active
    db.session.commit()
    action = 'aktiw' if cat.is_active else 'bloklanan'
    flash(f'Kategoriýa «{cat.name}» {action}.', 'success')
    return redirect(url_for('admin.direction_categories_list'))


# ── Analysis tools (Serişdeler) list ─────────────────────────────────────────

@admin_bp.route('/analysis-tools')
@admin_required
def analysis_tools_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    cat_filter = request.args.get('cat', 0, type=int)

    query = AnalysisTool.query

    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                AnalysisTool.name.ilike(like),
                AnalysisTool.analyses.any(Analysis.name.ilike(like)),
            )
        )

    if status_filter == 'active':
        query = query.filter(AnalysisTool.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(AnalysisTool.is_active == False)

    if cat_filter:
        query = query.filter(AnalysisTool.direction_category_id == cat_filter)

    tools = query.options(
        joinedload(AnalysisTool.category),
        joinedload(AnalysisTool.subcategory).joinedload(AnalysisToolSubcategory.category),
        joinedload(AnalysisTool.direction_category),
    ).order_by(AnalysisTool.name).all()
    all_categories = DoctorDirectionCategory.query.filter_by(is_active=True).order_by(DoctorDirectionCategory.name).all()

    return render_template(
        'admin/analysis_tools/list.html',
        tools=tools,
        search=search,
        status_filter=status_filter,
        cat_filter=cat_filter,
        all_categories=all_categories,
    )


# ── Create analysis tool ──────────────────────────────────────────────────────

@admin_bp.route('/analysis-tools/create', methods=['GET', 'POST'])
@admin_required
def analysis_tools_create():
    form = AnalysisToolForm()
    if form.validate_on_submit():
        analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
        tool = AnalysisTool(
            name=form.name.data.strip(),
            quantity=form.quantity.data,
            is_insurance=form.is_insurance.data,
            total_price=form.total_price.data,
            analyses=analyses,
            category_id=form.category_id.data or None,
            subcategory_id=form.subcategory_id.data or None,
            direction_category_id=form.direction_category_id.data or None,
        )
        db.session.add(tool)
        db.session.commit()
        flash(f'Serişde «{tool.name}» döredilen.', 'success')
        return redirect(url_for('admin.analysis_tools_list'))

    subcats_json = _subcats_as_json()
    return render_template('admin/analysis_tools/create.html', form=form, subcats_json=subcats_json)


# ── Edit analysis tool ────────────────────────────────────────────────────────

@admin_bp.route('/analysis-tools/<int:tool_id>/edit', methods=['GET', 'POST'])
@admin_required
def analysis_tools_edit(tool_id):
    tool = db.session.get(AnalysisTool, tool_id)
    if tool is None:
        abort(404)

    form = AnalysisToolForm(editing_tool=tool)
    if not form.is_submitted():
        form.name.data = tool.name
        form.quantity.data = tool.quantity
        form.is_insurance.data = tool.is_insurance
        form.total_price.data = tool.total_price
        form.analysis_ids.data = [a.id for a in tool.analyses]
        form.category_id.data = tool.category_id or 0
        form.subcategory_id.data = tool.subcategory_id or 0
        form.direction_category_id.data = tool.direction_category_id or 0

    if form.validate_on_submit():
        tool.name = form.name.data.strip()
        tool.quantity = form.quantity.data
        tool.is_insurance = form.is_insurance.data
        tool.total_price = form.total_price.data
        tool.analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
        tool.category_id = form.category_id.data or None
        tool.subcategory_id = form.subcategory_id.data or None
        tool.direction_category_id = form.direction_category_id.data or None
        db.session.commit()
        flash(f'Serişde «{tool.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.analysis_tools_list'))

    subcats_json = _subcats_as_json()
    return render_template('admin/analysis_tools/edit.html', form=form, tool=tool, subcats_json=subcats_json)


# ── Toggle analysis tool ──────────────────────────────────────────────────────

@admin_bp.route('/analysis-tools/<int:tool_id>/toggle', methods=['POST'])
@admin_required
def analysis_tools_toggle(tool_id):
    tool = db.session.get(AnalysisTool, tool_id)
    if tool is None:
        abort(404)

    tool.is_active = not tool.is_active
    db.session.commit()

    action = 'aktiw' if tool.is_active else 'bloklanan'
    flash(f'Serişde «{tool.name}» {action}.', 'success')
    return redirect(url_for('admin.analysis_tools_list'))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _subcats_as_json():
    """Plain list for the template's `| tojson` (safe against markup in names)."""
    subs = AnalysisToolSubcategory.query.filter_by(is_active=True).order_by(AnalysisToolSubcategory.name).all()
    return [{'id': s.id, 'name': s.name, 'category_id': s.category_id or 0} for s in subs]


# ── Analysis tool categories ──────────────────────────────────────────────────

@admin_bp.route('/tool-categories')
@admin_required
def tool_categories_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = AnalysisToolCategory.query
    if search:
        query = query.filter(AnalysisToolCategory.name.ilike(f'%{search}%'))
    if status_filter == 'active':
        query = query.filter(AnalysisToolCategory.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(AnalysisToolCategory.is_active == False)

    categories = query.order_by(AnalysisToolCategory.name).all()
    sub_counts = dict(
        db.session.query(
            AnalysisToolSubcategory.category_id,
            func.count(AnalysisToolSubcategory.id),
        )
        .filter(AnalysisToolSubcategory.category_id.isnot(None))
        .group_by(AnalysisToolSubcategory.category_id)
        .all()
    )
    return render_template(
        'admin/analysis_tool_categories/list.html',
        categories=categories,
        sub_counts=sub_counts,
        search=search,
        status_filter=status_filter,
    )


@admin_bp.route('/tool-categories/create', methods=['GET', 'POST'])
@admin_required
def tool_categories_create():
    form = AnalysisToolCategoryForm()
    if form.validate_on_submit():
        cat = AnalysisToolCategory(name=form.name.data.strip())
        db.session.add(cat)
        db.session.commit()
        flash(f'Kategoriýa «{cat.name}» döredilen.', 'success')
        return redirect(url_for('admin.tool_categories_list'))
    return render_template('admin/analysis_tool_categories/create.html', form=form)


@admin_bp.route('/tool-categories/<int:cat_id>/edit', methods=['GET', 'POST'])
@admin_required
def tool_categories_edit(cat_id):
    cat = db.session.get(AnalysisToolCategory, cat_id)
    if cat is None:
        abort(404)
    form = AnalysisToolCategoryForm(editing_category=cat)
    if not form.is_submitted():
        form.name.data = cat.name
    if form.validate_on_submit():
        cat.name = form.name.data.strip()
        db.session.commit()
        flash(f'Kategoriýa «{cat.name}» täzelenen.', 'success')
        return redirect(url_for('admin.tool_categories_list'))
    return render_template('admin/analysis_tool_categories/edit.html', form=form, cat=cat)


@admin_bp.route('/tool-categories/<int:cat_id>/toggle', methods=['POST'])
@admin_required
def tool_categories_toggle(cat_id):
    cat = db.session.get(AnalysisToolCategory, cat_id)
    if cat is None:
        abort(404)
    cat.is_active = not cat.is_active
    db.session.commit()
    action = 'aktiw' if cat.is_active else 'bloklanan'
    flash(f'Kategoriýa «{cat.name}» {action}.', 'success')
    return redirect(url_for('admin.tool_categories_list'))


# ── Analysis tool subcategories ───────────────────────────────────────────────

@admin_bp.route('/tool-subcategories')
@admin_required
def tool_subcategories_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    cat_filter = request.args.get('cat', 0, type=int)

    query = AnalysisToolSubcategory.query
    if search:
        query = query.filter(AnalysisToolSubcategory.name.ilike(f'%{search}%'))
    if status_filter == 'active':
        query = query.filter(AnalysisToolSubcategory.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(AnalysisToolSubcategory.is_active == False)
    if cat_filter:
        query = query.filter(AnalysisToolSubcategory.category_id == cat_filter)

    subcategories = query.options(joinedload(AnalysisToolSubcategory.category)).order_by(AnalysisToolSubcategory.name).all()
    all_categories = AnalysisToolCategory.query.filter_by(is_active=True).order_by(AnalysisToolCategory.name).all()
    return render_template(
        'admin/analysis_tool_subcategories/list.html',
        subcategories=subcategories,
        search=search,
        status_filter=status_filter,
        cat_filter=cat_filter,
        all_categories=all_categories,
    )


@admin_bp.route('/tool-subcategories/create', methods=['GET', 'POST'])
@admin_required
def tool_subcategories_create():
    form = AnalysisToolSubcategoryForm()
    if form.validate_on_submit():
        sub = AnalysisToolSubcategory(
            name=form.name.data.strip(),
            category_id=form.category_id.data,
        )
        db.session.add(sub)
        db.session.commit()
        flash(f'Kiçi kategoriýa «{sub.name}» döredilen.', 'success')
        return redirect(url_for('admin.tool_subcategories_list'))
    return render_template('admin/analysis_tool_subcategories/create.html', form=form)


@admin_bp.route('/tool-subcategories/<int:sub_id>/edit', methods=['GET', 'POST'])
@admin_required
def tool_subcategories_edit(sub_id):
    sub = db.session.get(AnalysisToolSubcategory, sub_id)
    if sub is None:
        abort(404)
    form = AnalysisToolSubcategoryForm(editing_subcategory=sub)
    if not form.is_submitted():
        form.name.data = sub.name
        form.category_id.data = sub.category_id or 0
    if form.validate_on_submit():
        sub.name = form.name.data.strip()
        sub.category_id = form.category_id.data
        db.session.commit()
        flash(f'Kiçi kategoriýa «{sub.name}» täzelenen.', 'success')
        return redirect(url_for('admin.tool_subcategories_list'))
    return render_template('admin/analysis_tool_subcategories/edit.html', form=form, sub=sub)


@admin_bp.route('/tool-subcategories/<int:sub_id>/toggle', methods=['POST'])
@admin_required
def tool_subcategories_toggle(sub_id):
    sub = db.session.get(AnalysisToolSubcategory, sub_id)
    if sub is None:
        abort(404)
    sub.is_active = not sub.is_active
    db.session.commit()
    action = 'aktiw' if sub.is_active else 'bloklanan'
    flash(f'Kiçi kategoriýa «{sub.name}» {action}.', 'success')
    return redirect(url_for('admin.tool_subcategories_list'))


# ── Blanks (Blanklar) list ────────────────────────────────────────────────────

@admin_bp.route('/blanks')
@admin_required
def blanks_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    cat_filter = request.args.get('cat', 0, type=int)

    query = Blank.query

    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(
                Blank.name.ilike(like),
                Blank.analyses.any(Analysis.name.ilike(like)),
            )
        )

    if status_filter == 'active':
        query = query.filter(Blank.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(Blank.is_active == False)

    if cat_filter:
        query = query.filter(Blank.category_id == cat_filter)

    blanks = query.options(joinedload(Blank.category)).order_by(Blank.name).all()
    all_categories = DoctorDirectionCategory.query.filter_by(is_active=True).order_by(DoctorDirectionCategory.name).all()

    return render_template(
        'admin/blanks/list.html',
        blanks=blanks,
        search=search,
        status_filter=status_filter,
        cat_filter=cat_filter,
        all_categories=all_categories,
    )


# ── Create blank ──────────────────────────────────────────────────────────────

@admin_bp.route('/blanks/create', methods=['GET', 'POST'])
@admin_required
def blanks_create():
    form = BlankForm()
    if form.validate_on_submit():
        analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
        blank = Blank(
            name=form.name.data.strip(),
            quantity=form.quantity.data,
            is_insurance=form.is_insurance.data,
            total_price=form.total_price.data,
            analyses=analyses,
            category_id=form.category_id.data or None,
        )
        db.session.add(blank)
        db.session.commit()
        flash(f'Blank «{blank.name}» döredilen.', 'success')
        return redirect(url_for('admin.blanks_list'))

    return render_template('admin/blanks/create.html', form=form)


# ── Edit blank ────────────────────────────────────────────────────────────────

@admin_bp.route('/blanks/<int:blank_id>/edit', methods=['GET', 'POST'])
@admin_required
def blanks_edit(blank_id):
    blank = db.session.get(Blank, blank_id)
    if blank is None:
        abort(404)

    form = BlankForm(editing_blank=blank)
    if not form.is_submitted():
        form.name.data = blank.name
        form.quantity.data = blank.quantity
        form.is_insurance.data = blank.is_insurance
        form.total_price.data = blank.total_price
        form.analysis_ids.data = [a.id for a in blank.analyses]
        form.category_id.data = blank.category_id or 0

    if form.validate_on_submit():
        blank.name = form.name.data.strip()
        blank.quantity = form.quantity.data
        blank.is_insurance = form.is_insurance.data
        blank.total_price = form.total_price.data
        blank.analyses = Analysis.query.filter(Analysis.id.in_(form.analysis_ids.data)).all()
        blank.category_id = form.category_id.data or None
        db.session.commit()
        flash(f'Blank «{blank.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.blanks_list'))

    return render_template('admin/blanks/edit.html', form=form, blank=blank)


# ── Toggle blank ──────────────────────────────────────────────────────────────

@admin_bp.route('/blanks/<int:blank_id>/toggle', methods=['POST'])
@admin_required
def blanks_toggle(blank_id):
    blank = db.session.get(Blank, blank_id)
    if blank is None:
        abort(404)

    blank.is_active = not blank.is_active
    db.session.commit()

    action = 'aktiw' if blank.is_active else 'bloklanan'
    flash(f'Blank «{blank.name}» {action}.', 'success')
    return redirect(url_for('admin.blanks_list'))


# ── Daily report ─────────────────────────────────────────────────────────────

@admin_bp.route('/daily-report')
@admin_required
def daily_report():
    page = request.args.get('page', 1, type=int)
    pagination = (
        db.session.query(
            func.date(Examination.paid_at).label('day'),
            func.count(Examination.id).label('cnt'),
        )
        .filter(Examination.paid_at.isnot(None))
        .group_by(func.date(Examination.paid_at))
        .order_by(func.date(Examination.paid_at).desc())
        .paginate(page=page, per_page=15, error_out=False)
    )
    # func.date() hands back a date on MySQL and a string on SQLite; the page
    # prints one day the same way whichever engine answered.
    rows = [
        {'day': row.day.strftime('%d.%m.%Y') if hasattr(row.day, 'strftime') else row.day,
         'cnt': row.cnt}
        for row in pagination.items
    ]
    return render_template(
        'admin/reports/daily.html',
        rows=rows,
        pagination=pagination,
    )


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


# ── Departments (Bölümler) ────────────────────────────────────────────────────

@admin_bp.route('/departments')
@admin_required
def departments_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = Department.query
    if search:
        query = query.filter(Department.name.ilike(f'%{search}%'))
    if status_filter == 'active':
        query = query.filter(Department.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(Department.is_active == False)

    departments = query.order_by(Department.name).all()
    room_counts = dict(
        db.session.query(Room.department_id, func.count(Room.id))
        .group_by(Room.department_id)
        .all()
    )
    return render_template(
        'admin/departments/list.html',
        departments=departments,
        room_counts=room_counts,
        search=search,
        status_filter=status_filter,
    )


@admin_bp.route('/departments/create', methods=['GET', 'POST'])
@admin_required
def departments_create():
    form = DepartmentForm()
    if form.validate_on_submit():
        dep = Department(name=form.name.data.strip())
        db.session.add(dep)
        db.session.commit()
        flash(f'Bölüm «{dep.name}» döredilen.', 'success')
        return redirect(url_for('admin.departments_list'))
    return render_template('admin/departments/create.html', form=form)


@admin_bp.route('/departments/<int:dep_id>/edit', methods=['GET', 'POST'])
@admin_required
def departments_edit(dep_id):
    dep = db.session.get(Department, dep_id)
    if dep is None:
        abort(404)
    form = DepartmentForm(editing_department=dep)
    if not form.is_submitted():
        form.name.data = dep.name
    if form.validate_on_submit():
        dep.name = form.name.data.strip()
        db.session.commit()
        flash(f'Bölüm «{dep.name}» täzelenen.', 'success')
        return redirect(url_for('admin.departments_list'))
    return render_template('admin/departments/edit.html', form=form, dep=dep)


@admin_bp.route('/departments/<int:dep_id>/toggle', methods=['POST'])
@admin_required
def departments_toggle(dep_id):
    dep = db.session.get(Department, dep_id)
    if dep is None:
        abort(404)
    dep.is_active = not dep.is_active
    db.session.commit()
    action = 'aktiw' if dep.is_active else 'bloklanan'
    flash(f'Bölüm «{dep.name}» {action}.', 'success')
    return redirect(url_for('admin.departments_list'))


# ── Users ↔ departments (Ulanyjylaryň bölümleri) ──────────────────────────────

@admin_bp.route('/user-departments')
@admin_required
def user_departments_list():
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

    users = query.options(joinedload(User.departments)).order_by(User.full_name).all()
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()

    return render_template(
        'admin/user_departments/list.html',
        users=users,
        departments=departments,
        search=search,
        role_filter=role_filter,
        roles=User.ROLES,
    )


@admin_bp.route('/user-departments/<int:user_id>', methods=['POST'])
@admin_required
def user_departments_update(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    back = url_for('admin.user_departments_list',
                   q=request.form.get('q', '').strip() or None,
                   role=request.form.get('role', '').strip() or None)

    if not user.can_have_departments():
        flash(f'«{user.get_role_display()}» roluna bölüm bellenmeýär.', 'danger')
        return redirect(back)

    selected_ids = request.form.getlist('department_ids', type=int)
    user.departments = (
        Department.query.filter(Department.id.in_(selected_ids)).all() if selected_ids else []
    )
    db.session.commit()

    flash(f'«{user.full_name}» ulanyjynyň bölümleri täzelendi.', 'success')
    return redirect(back)


# ── Room types (Palata görnüşleri) ────────────────────────────────────────────

@admin_bp.route('/room-types')
@admin_required
def room_types_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = RoomType.query
    if search:
        query = query.filter(RoomType.name.ilike(f'%{search}%'))
    if status_filter == 'active':
        query = query.filter(RoomType.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(RoomType.is_active == False)

    room_types = query.order_by(RoomType.name).all()
    room_counts = dict(
        db.session.query(Room.room_type_id, func.count(Room.id))
        .group_by(Room.room_type_id)
        .all()
    )
    return render_template(
        'admin/room_types/list.html',
        room_types=room_types,
        room_counts=room_counts,
        search=search,
        status_filter=status_filter,
    )


@admin_bp.route('/room-types/create', methods=['GET', 'POST'])
@admin_required
def room_types_create():
    form = RoomTypeForm()
    if form.validate_on_submit():
        rt = RoomType(name=form.name.data.strip())
        db.session.add(rt)
        db.session.commit()
        flash(f'Palata görnüşi «{rt.name}» döredilen.', 'success')
        return redirect(url_for('admin.room_types_list'))
    return render_template('admin/room_types/create.html', form=form)


@admin_bp.route('/room-types/<int:type_id>/edit', methods=['GET', 'POST'])
@admin_required
def room_types_edit(type_id):
    rt = db.session.get(RoomType, type_id)
    if rt is None:
        abort(404)
    form = RoomTypeForm(editing_room_type=rt)
    if not form.is_submitted():
        form.name.data = rt.name
    if form.validate_on_submit():
        rt.name = form.name.data.strip()
        db.session.commit()
        flash(f'Palata görnüşi «{rt.name}» täzelenen.', 'success')
        return redirect(url_for('admin.room_types_list'))
    return render_template('admin/room_types/edit.html', form=form, room_type=rt)


@admin_bp.route('/room-types/<int:type_id>/toggle', methods=['POST'])
@admin_required
def room_types_toggle(type_id):
    rt = db.session.get(RoomType, type_id)
    if rt is None:
        abort(404)
    rt.is_active = not rt.is_active
    db.session.commit()
    action = 'aktiw' if rt.is_active else 'bloklanan'
    flash(f'Palata görnüşi «{rt.name}» {action}.', 'success')
    return redirect(url_for('admin.room_types_list'))


# ── Rooms (Palatalar) ─────────────────────────────────────────────────────────

@admin_bp.route('/rooms')
@admin_required
def rooms_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    dep_filter = request.args.get('dep', 0, type=int)
    type_filter = request.args.get('type', 0, type=int)

    query = Room.query
    if search:
        query = query.filter(Room.name.ilike(f'%{search}%'))
    if status_filter == 'active':
        query = query.filter(Room.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(Room.is_active == False)
    if dep_filter:
        query = query.filter(Room.department_id == dep_filter)
    if type_filter:
        query = query.filter(Room.room_type_id == type_filter)

    rooms = (
        query.options(joinedload(Room.department), joinedload(Room.room_type))
        .join(Room.department)
        .order_by(Department.name, Room.name)
        .all()
    )
    bed_counts = dict(
        db.session.query(Bed.room_id, func.count(Bed.id))
        .group_by(Bed.room_id)
        .all()
    )
    all_departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    all_room_types = RoomType.query.filter_by(is_active=True).order_by(RoomType.name).all()

    return render_template(
        'admin/rooms/list.html',
        rooms=rooms,
        bed_counts=bed_counts,
        search=search,
        status_filter=status_filter,
        dep_filter=dep_filter,
        type_filter=type_filter,
        all_departments=all_departments,
        all_room_types=all_room_types,
    )


@admin_bp.route('/rooms/create', methods=['GET', 'POST'])
@admin_required
def rooms_create():
    form = RoomForm()
    if form.validate_on_submit():
        room = Room(
            name=form.name.data.strip(),
            room_type_id=form.room_type_id.data,
            department_id=form.department_id.data,
        )
        db.session.add(room)
        db.session.commit()
        flash(f'Palata «{room.name}» döredilen.', 'success')
        return redirect(url_for('admin.rooms_list'))
    return render_template('admin/rooms/create.html', form=form)


@admin_bp.route('/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@admin_required
def rooms_edit(room_id):
    room = db.session.get(Room, room_id)
    if room is None:
        abort(404)
    form = RoomForm(editing_room=room)
    if not form.is_submitted():
        form.name.data = room.name
        form.room_type_id.data = room.room_type_id or 0
        form.department_id.data = room.department_id or 0
    if form.validate_on_submit():
        room.name = form.name.data.strip()
        room.room_type_id = form.room_type_id.data
        room.department_id = form.department_id.data
        db.session.commit()
        flash(f'Palata «{room.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.rooms_list'))
    return render_template('admin/rooms/edit.html', form=form, room=room)


@admin_bp.route('/rooms/<int:room_id>/toggle', methods=['POST'])
@admin_required
def rooms_toggle(room_id):
    room = db.session.get(Room, room_id)
    if room is None:
        abort(404)
    room.is_active = not room.is_active
    db.session.commit()
    action = 'aktiw' if room.is_active else 'bloklanan'
    flash(f'Palata «{room.name}» {action}.', 'success')
    return redirect(url_for('admin.rooms_list'))


# ── Beds (Krowatlar) ──────────────────────────────────────────────────────────

@admin_bp.route('/beds')
@admin_required
def beds_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    dep_filter = request.args.get('dep', 0, type=int)
    room_filter = request.args.get('room', 0, type=int)

    query = Bed.query.join(Bed.room)

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Bed.name.ilike(like), Room.name.ilike(like)))
    if status_filter == 'active':
        query = query.filter(Bed.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(Bed.is_active == False)
    if dep_filter:
        query = query.filter(Room.department_id == dep_filter)
    if room_filter:
        query = query.filter(Bed.room_id == room_filter)

    beds = (
        query.options(contains_eager(Bed.room).joinedload(Room.department))
        .join(Room.department)
        .order_by(Department.name, Room.name, Bed.name)
        .all()
    )
    all_departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    all_rooms = (
        Room.query.filter_by(is_active=True)
        .options(joinedload(Room.department))
        .join(Room.department)
        .order_by(Department.name, Room.name)
        .all()
    )

    return render_template(
        'admin/beds/list.html',
        beds=beds,
        search=search,
        status_filter=status_filter,
        dep_filter=dep_filter,
        room_filter=room_filter,
        all_departments=all_departments,
        all_rooms=all_rooms,
    )


@admin_bp.route('/beds/create', methods=['GET', 'POST'])
@admin_required
def beds_create():
    form = BedForm()
    if form.validate_on_submit():
        bed = Bed(
            name=form.name.data.strip(),
            room_id=form.room_id.data,
            price=form.price.data,
            is_insurance=form.is_insurance.data,
        )
        db.session.add(bed)
        db.session.commit()
        flash(f'Krowat «{bed.name}» döredilen.', 'success')
        return redirect(url_for('admin.beds_list'))
    return render_template('admin/beds/create.html', form=form)


@admin_bp.route('/beds/<int:bed_id>/edit', methods=['GET', 'POST'])
@admin_required
def beds_edit(bed_id):
    bed = db.session.get(Bed, bed_id)
    if bed is None:
        abort(404)
    form = BedForm(editing_bed=bed)
    if not form.is_submitted():
        form.name.data = bed.name
        form.room_id.data = bed.room_id or 0
        form.price.data = bed.price
        form.is_insurance.data = bed.is_insurance
    if form.validate_on_submit():
        bed.name = form.name.data.strip()
        bed.room_id = form.room_id.data
        bed.price = form.price.data
        bed.is_insurance = form.is_insurance.data
        db.session.commit()
        flash(f'Krowat «{bed.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.beds_list'))
    return render_template('admin/beds/edit.html', form=form, bed=bed)


@admin_bp.route('/beds/<int:bed_id>/toggle', methods=['POST'])
@admin_required
def beds_toggle(bed_id):
    bed = db.session.get(Bed, bed_id)
    if bed is None:
        abort(404)
    bed.is_active = not bed.is_active
    db.session.commit()
    action = 'aktiw' if bed.is_active else 'bloklanan'
    flash(f'Krowat «{bed.name}» {action}.', 'success')
    return redirect(url_for('admin.beds_list'))


# ── Meals (Naharlar) ──────────────────────────────────────────────────────────

@admin_bp.route('/meals')
@admin_required
def meals_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    dep_filter = request.args.get('dep', 0, type=int)

    query = Meal.query

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Meal.name.ilike(like), Meal.note.ilike(like)))
    if status_filter == 'active':
        query = query.filter(Meal.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(Meal.is_active == False)
    if dep_filter:
        query = query.filter(Meal.departments.any(Department.id == dep_filter))

    meals = query.order_by(Meal.name).all()
    all_departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()

    return render_template(
        'admin/meals/list.html',
        meals=meals,
        search=search,
        status_filter=status_filter,
        dep_filter=dep_filter,
        all_departments=all_departments,
    )


@admin_bp.route('/meals/create', methods=['GET', 'POST'])
@admin_required
def meals_create():
    form = MealForm()
    if form.validate_on_submit():
        meal = Meal(
            name=form.name.data.strip(),
            note=(form.note.data or '').strip() or None,
            price=form.price.data,
            is_insurance=form.is_insurance.data,
        )
        meal.departments = Department.query.filter(Department.id.in_(form.department_ids.data)).all()
        db.session.add(meal)
        db.session.commit()
        flash(f'Nahar «{meal.name}» döredilen.', 'success')
        return redirect(url_for('admin.meals_list'))
    return render_template('admin/meals/create.html', form=form)


@admin_bp.route('/meals/<int:meal_id>/edit', methods=['GET', 'POST'])
@admin_required
def meals_edit(meal_id):
    meal = db.session.get(Meal, meal_id)
    if meal is None:
        abort(404)
    form = MealForm(editing_meal=meal)
    if not form.is_submitted():
        form.name.data = meal.name
        form.note.data = meal.note
        form.price.data = meal.price
        form.is_insurance.data = meal.is_insurance
        form.department_ids.data = [d.id for d in meal.departments]
    if form.validate_on_submit():
        meal.name = form.name.data.strip()
        meal.note = (form.note.data or '').strip() or None
        meal.price = form.price.data
        meal.is_insurance = form.is_insurance.data
        meal.departments = Department.query.filter(Department.id.in_(form.department_ids.data)).all()
        db.session.commit()
        flash(f'Nahar «{meal.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.meals_list'))
    return render_template('admin/meals/edit.html', form=form, meal=meal)


@admin_bp.route('/meals/<int:meal_id>/toggle', methods=['POST'])
@admin_required
def meals_toggle(meal_id):
    meal = db.session.get(Meal, meal_id)
    if meal is None:
        abort(404)
    meal.is_active = not meal.is_active
    db.session.commit()
    action = 'aktiw' if meal.is_active else 'bloklanan'
    flash(f'Nahar «{meal.name}» {action}.', 'success')
    return redirect(url_for('admin.meals_list'))


# ── Medicines (Dermanlar) ─────────────────────────────────────────────────────

@admin_bp.route('/medicines')
@admin_required
def medicines_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    unit_filter = request.args.get('unit', '').strip()

    query = Medicine.query

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Medicine.name.ilike(like), Medicine.note.ilike(like)))
    if status_filter == 'active':
        query = query.filter(Medicine.is_active == True)  # noqa: E712
    elif status_filter == 'blocked':
        query = query.filter(Medicine.is_active == False)  # noqa: E712
    if unit_filter in Medicine.UNITS:
        query = query.filter(Medicine.unit == unit_filter)

    medicines = query.order_by(Medicine.name).all()

    return render_template(
        'admin/medicines/list.html',
        medicines=medicines,
        search=search,
        status_filter=status_filter,
        unit_filter=unit_filter,
        units=Medicine.UNITS,
    )


@admin_bp.route('/medicines/create', methods=['GET', 'POST'])
@admin_required
def medicines_create():
    form = MedicineForm()
    if form.validate_on_submit():
        medicine = Medicine(
            name=form.name.data.strip(),
            unit=form.unit.data,
            note=(form.note.data or '').strip() or None,
            price=form.price.data,
            is_insurance=form.is_insurance.data,
        )
        db.session.add(medicine)
        db.session.commit()
        flash(f'Derman «{medicine.name}» döredilen.', 'success')
        return redirect(url_for('admin.medicines_list'))
    return render_template('admin/medicines/create.html', form=form)


@admin_bp.route('/medicines/<int:medicine_id>/edit', methods=['GET', 'POST'])
@admin_required
def medicines_edit(medicine_id):
    medicine = db.session.get(Medicine, medicine_id)
    if medicine is None:
        abort(404)
    form = MedicineForm(editing_medicine=medicine)
    if not form.is_submitted():
        form.name.data = medicine.name
        form.unit.data = medicine.unit
        form.note.data = medicine.note
        form.price.data = medicine.price
        form.is_insurance.data = medicine.is_insurance
    if form.validate_on_submit():
        medicine.name = form.name.data.strip()
        medicine.unit = form.unit.data
        medicine.note = (form.note.data or '').strip() or None
        medicine.price = form.price.data
        medicine.is_insurance = form.is_insurance.data
        db.session.commit()
        flash(f'Derman «{medicine.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.medicines_list'))
    return render_template('admin/medicines/edit.html', form=form, medicine=medicine)


@admin_bp.route('/medicines/<int:medicine_id>/toggle', methods=['POST'])
@admin_required
def medicines_toggle(medicine_id):
    medicine = db.session.get(Medicine, medicine_id)
    if medicine is None:
        abort(404)
    medicine.is_active = not medicine.is_active
    db.session.commit()
    action = 'aktiw' if medicine.is_active else 'bloklanan'
    flash(f'Derman «{medicine.name}» {action}.', 'success')
    return redirect(url_for('admin.medicines_list'))


# ── Operations (Operasiýalar) ─────────────────────────────────────────────────

@admin_bp.route('/operations')
@admin_required
def operations_list():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = Operation.query

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Operation.name.ilike(like), Operation.note.ilike(like)))
    if status_filter == 'active':
        query = query.filter(Operation.is_active == True)  # noqa: E712
    elif status_filter == 'blocked':
        query = query.filter(Operation.is_active == False)  # noqa: E712

    operations = query.order_by(Operation.name).all()

    return render_template(
        'admin/operations/list.html',
        operations=operations,
        search=search,
        status_filter=status_filter,
    )


@admin_bp.route('/operations/create', methods=['GET', 'POST'])
@admin_required
def operations_create():
    form = OperationForm()
    if form.validate_on_submit():
        operation = Operation(
            name=form.name.data.strip(),
            note=(form.note.data or '').strip() or None,
            price=form.price.data,
            is_insurance=form.is_insurance.data,
        )
        db.session.add(operation)
        db.session.commit()
        flash(f'Operasiýa «{operation.name}» döredilen.', 'success')
        return redirect(url_for('admin.operations_list'))
    return render_template('admin/operations/create.html', form=form)


@admin_bp.route('/operations/<int:operation_id>/edit', methods=['GET', 'POST'])
@admin_required
def operations_edit(operation_id):
    operation = db.session.get(Operation, operation_id)
    if operation is None:
        abort(404)
    form = OperationForm(editing_operation=operation)
    if not form.is_submitted():
        form.name.data = operation.name
        form.note.data = operation.note
        form.price.data = operation.price
        form.is_insurance.data = operation.is_insurance
    if form.validate_on_submit():
        operation.name = form.name.data.strip()
        operation.note = (form.note.data or '').strip() or None
        operation.price = form.price.data
        operation.is_insurance = form.is_insurance.data
        db.session.commit()
        flash(f'Operasiýa «{operation.name}» maglumatlary täzelenen.', 'success')
        return redirect(url_for('admin.operations_list'))
    return render_template('admin/operations/edit.html', form=form, operation=operation)


@admin_bp.route('/operations/<int:operation_id>/toggle', methods=['POST'])
@admin_required
def operations_toggle(operation_id):
    operation = db.session.get(Operation, operation_id)
    if operation is None:
        abort(404)
    operation.is_active = not operation.is_active
    db.session.commit()
    action = 'aktiw' if operation.is_active else 'bloklanan'
    flash(f'Operasiýa «{operation.name}» {action}.', 'success')
    return redirect(url_for('admin.operations_list'))
