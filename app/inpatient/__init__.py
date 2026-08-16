from flask import Blueprint

inpatient_bp = Blueprint('inpatient', __name__)

from app.inpatient import routes  # noqa: E402, F401
