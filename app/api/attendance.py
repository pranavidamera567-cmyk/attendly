from datetime import date

from flask import Blueprint, current_app, jsonify, request

from .. import rules
from ..auth import api_auth
from ..models import ADMIN, ATTENDANCE_STATUSES, Attendance, User, db
from ..util import bad, commit, paginate, parse_date, parse_month, parse_time

bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")
EDIT_WINDOW_DAYS = 7


def now():
    return current_app.config["NOW"]()


def to_dict(a):
    return {"id": a.id, "user_id": a.user_id, "employee": a.user.name, "department": a.user.department.name,
            "date": a.date.isoformat(), "check_in": a.check_in.strftime("%H:%M") if a.check_in else None,
            "check_out": a.check_out.strftime("%H:%M") if a.check_out else None, "status": a.status,
            "hours": rules.hours_between(a.check_in, a.check_out), "late": rules.is_late(a.check_in), "note": a.note}


def blocking_problem(user_id, d):
    if d.weekday() >= 5 or not rules.is_working_day(d):
        return "That date is a weekend or public holiday"
    if rules.approved_leave_on(user_id, d):
        return "That date is covered by approved leave"
    return None


@bp.get("/today")
@api_auth()
def today_record(user):
    a = Attendance.query.filter_by(user_id=user.id, date=now().date()).first()
    return jsonify(to_dict(a) if a else None)


@bp.post("/check-in")
@api_auth()
def check_in(user):
    t = now()
    problem = blocking_problem(user.id, t.date())
    if problem:
        return bad(problem, 409)
    if Attendance.query.filter_by(user_id=user.id, date=t.date()).first():
        return bad("You have already checked in today", 409)
    a = Attendance(user_id=user.id, date=t.date(), check_in=t.time().replace(second=0, microsecond=0),
                   status=(request.get_json(silent=True) or {}).get("status", "present"))
    if a.status not in ("present", "remote"):
        return bad("status must be present or remote")
    db.session.add(a)
    commit()
    return jsonify(to_dict(a)), 201


@bp.post("/check-out")
@api_auth()
def check_out(user):
    t = now()
    a = Attendance.query.filter_by(user_id=user.id, date=t.date()).first()
    if a is None or a.check_in is None:
        return bad("You have not checked in today", 409)
    if a.check_out:
        return bad("You have already checked out today", 409)
    out = t.time().replace(second=0, microsecond=0)
    if out <= a.check_in:
        return bad("Check-out must be after check-in", 409)
    a.check_out = out
    commit()
    return jsonify(to_dict(a))


def _fill(a, b, actor):
    """Validates and applies form fields; returns an error response or None."""
    try:
        # fields missing from the body keep their current value, so a PUT may change just one of them
        d = parse_date(b.get("date"), "date") if "date" in b or a.date is None else a.date
        check_in = parse_time(b["check_in"], "check_in") if "check_in" in b else a.check_in
        check_out = parse_time(b["check_out"], "check_out") if "check_out" in b else a.check_out
    except ValueError as e:
        return bad(str(e))
    status = b.get("status", a.status or "present")
    if status not in ATTENDANCE_STATUSES:
        return bad(f"status must be one of {', '.join(ATTENDANCE_STATUSES)}")
    if d > now().date():
        return bad("Attendance cannot be recorded for a future date")
    if actor.role != ADMIN and (now().date() - d).days > EDIT_WINDOW_DAYS:
        return bad(f"Entries older than {EDIT_WINDOW_DAYS} days can only be changed by an admin", 403)
    if check_in is None:
        return bad("A check-in time is required")
    if check_out is not None and check_out <= check_in:
        return bad("Check-out must be after check-in")
    problem = blocking_problem(a.user_id, d)
    if problem:
        return bad(problem, 409)
    a.date, a.check_in, a.check_out, a.status = d, check_in, check_out, status
    a.note = (b.get("note", a.note) or "")[:200]
    return None


@bp.post("")
@api_auth()
def create(user):
    b = request.get_json(silent=True) or {}
    target_id = b.get("user_id", user.id)
    if target_id != user.id and user.role != ADMIN:
        return bad("You can only record your own attendance", 403)
    if db.session.get(User, target_id) is None:
        return bad("Unknown employee", 404)
    a = Attendance(user_id=target_id)
    err = _fill(a, {**b, "date": b.get("date")}, user)
    if err:
        return err
    if Attendance.query.filter_by(user_id=target_id, date=a.date).first():
        return bad("Attendance for that date already exists; edit it instead", 409)
    db.session.add(a)
    commit()
    return jsonify(to_dict(a)), 201


@bp.put("/<int:att_id>")
@api_auth()
def update(user, att_id):
    a = db.session.get(Attendance, att_id)
    if a is None or (a.user_id != user.id and user.role != ADMIN):
        return bad("Attendance record not found", 404)
    err = _fill(a, request.get_json(silent=True) or {}, user)
    if err:
        return err
    commit()
    return jsonify(to_dict(a))


@bp.get("")
@api_auth()
def list_records(user):
    try:
        year, month = parse_month(request.args.get("month"), now().date())
    except ValueError as e:
        return bad(str(e))
    first, last = rules.month_bounds(year, month)
    ids = [u.id for u in rules.visible_users(user)]
    q = Attendance.query.join(User, Attendance.user_id == User.id).filter(
        Attendance.user_id.in_(ids), Attendance.date >= first, Attendance.date <= last)
    if request.args.get("user_id", type=int):
        q = q.filter(Attendance.user_id == request.args.get("user_id", type=int))
    if request.args.get("department_id", type=int):
        q = q.filter(User.department_id == request.args.get("department_id", type=int))
    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.filter(db.func.lower(User.name).like(f"%{term}%"))
    return paginate(q.order_by(Attendance.date.desc(), User.name), to_dict)
