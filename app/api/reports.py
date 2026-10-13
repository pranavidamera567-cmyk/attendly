"""Attendance and leave summaries (per employee, per month, per department) with CSV exports."""
from collections import defaultdict

from flask import Blueprint, current_app, jsonify, request

from .. import rules
from ..auth import api_auth
from ..models import ADMIN, APPROVED, MANAGER, Attendance, Department, LeaveRequest, User, db
from ..util import bad, csv_response, parse_month

bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def today():
    return current_app.config["NOW"]().date()


def _overlap_days(req, first, last, holidays):
    start, end = max(req.start_date, first), min(req.end_date, last)
    return rules.business_days(start, end, holidays) if start <= end else 0


def employee_rows(actor, year, month, department_id=None, term=None):
    """One summary row per visible employee for the month. 'Expected' days run up to today in the current month."""
    first, last = rules.month_bounds(year, month)
    horizon = min(last, today())
    q = rules.visible_users(actor).join(Department)
    if department_id:
        q = q.filter(User.department_id == department_id)
    if term:
        q = q.filter(db.func.lower(User.name).like(f"%{term.lower()}%"))
    users = q.order_by(Department.name, User.name).all()
    if horizon < first:                                    # a future month has nothing to report yet
        expected, holidays = 0, set()
    else:
        holidays = rules.holidays_between(first, horizon)
        expected = rules.business_days(first, horizon, holidays)
    ids = [u.id for u in users]
    att = defaultdict(list)
    leave = defaultdict(list)
    if ids and expected:
        for a in Attendance.query.filter(Attendance.user_id.in_(ids), Attendance.date >= first,
                                         Attendance.date <= horizon):
            att[a.user_id].append(a)
        for r in LeaveRequest.query.filter(LeaveRequest.user_id.in_(ids), LeaveRequest.status == APPROVED,
                                           LeaveRequest.start_date <= horizon, LeaveRequest.end_date >= first):
            leave[r.user_id].append(r)
    rows = []
    for u in users:
        records = att[u.id]
        full = sum(1 for a in records if a.status in ("present", "remote"))
        half = sum(1 for a in records if a.status == "half_day")
        attended = full + 0.5 * half
        leave_days = sum(_overlap_days(r, first, horizon, holidays) for r in leave[u.id])
        due = max(expected - leave_days, 0)
        rows.append({"user_id": u.id, "employee": u.name, "department": u.department.name,
                     "expected_days": expected, "present_days": full, "half_days": half,
                     "leave_days": leave_days, "absent_days": round(max(due - attended, 0), 1),
                     "late_count": sum(1 for a in records if rules.is_late(a.check_in)),
                     "total_hours": round(sum(rules.hours_between(a.check_in, a.check_out) for a in records), 1),
                     "attendance_rate": round(100 * min(attended / due, 1), 1) if due else None})
    return rows


def department_rows(rows):
    agg = {}
    for r in rows:
        d = agg.setdefault(r["department"], {"department": r["department"], "headcount": 0, "expected_days": 0,
                                             "attended_days": 0.0, "leave_days": 0, "absent_days": 0.0,
                                             "late_count": 0, "total_hours": 0.0})
        d["headcount"] += 1
        d["expected_days"] += r["expected_days"]
        d["attended_days"] += r["present_days"] + 0.5 * r["half_days"]
        d["leave_days"] += r["leave_days"]
        d["absent_days"] += r["absent_days"]
        d["late_count"] += r["late_count"]
        d["total_hours"] += r["total_hours"]
    out = []
    for d in agg.values():
        due = d["expected_days"] - d["leave_days"]
        d["attendance_rate"] = round(100 * min(d["attended_days"] / due, 1), 1) if due > 0 else None
        d.update(attended_days=round(d["attended_days"], 1), absent_days=round(d["absent_days"], 1),
                 total_hours=round(d["total_hours"], 1))
        out.append(d)
    return sorted(out, key=lambda d: d["department"])


def _params(user):
    year, month = parse_month(request.args.get("month"), today())
    return employee_rows(user, year, month, request.args.get("department_id", type=int), request.args.get("q"))


@bp.get("/attendance-summary")
@api_auth(MANAGER, ADMIN)
def attendance_summary(user):
    try:
        return jsonify(_params(user))
    except ValueError as e:
        return bad(str(e))


@bp.get("/attendance-summary.csv")
@api_auth(MANAGER, ADMIN)
def attendance_summary_csv(user):
    try:
        rows = _params(user)
    except ValueError as e:
        return bad(str(e))
    cols = ["employee", "department", "expected_days", "present_days", "half_days", "leave_days", "absent_days",
            "late_count", "total_hours", "attendance_rate"]
    return csv_response(f"attendance-{request.args.get('month') or today().strftime('%Y-%m')}.csv", cols,
                        [[r[c] for c in cols] for r in rows])


@bp.get("/department-summary")
@api_auth(MANAGER, ADMIN)
def department_summary(user):
    try:
        return jsonify(department_rows(_params(user)))
    except ValueError as e:
        return bad(str(e))


@bp.get("/department-summary.csv")
@api_auth(MANAGER, ADMIN)
def department_summary_csv(user):
    try:
        rows = department_rows(_params(user))
    except ValueError as e:
        return bad(str(e))
    cols = ["department", "headcount", "expected_days", "attended_days", "leave_days", "absent_days", "late_count",
            "total_hours", "attendance_rate"]
    return csv_response(f"departments-{request.args.get('month') or today().strftime('%Y-%m')}.csv", cols,
                        [[r[c] for c in cols] for r in rows])


@bp.get("/employee-monthly")
@api_auth()
def employee_monthly(user):
    """One employee, month by month for a year: attended days, leave days, late arrivals, hours."""
    target = request.args.get("user_id", user.id, type=int)
    if not rules.can_view_user(user, target):
        return bad("You cannot view that employee", 403)
    year = request.args.get("year", today().year, type=int)
    months = []
    for m in range(1, 13):
        first, last = rules.month_bounds(year, m)
        if first > today():
            break
        records = Attendance.query.filter(Attendance.user_id == target, Attendance.date >= first,
                                          Attendance.date <= last).all()
        hol = rules.holidays_between(first, last)
        leave = sum(_overlap_days(r, first, last, hol) for r in LeaveRequest.query.filter(
            LeaveRequest.user_id == target, LeaveRequest.status == APPROVED, LeaveRequest.start_date <= last,
            LeaveRequest.end_date >= first))
        months.append({"month": f"{year}-{m:02d}",
                       "attended_days": sum(1.0 if a.status != "half_day" else 0.5 for a in records),
                       "leave_days": leave, "late_count": sum(1 for a in records if rules.is_late(a.check_in)),
                       "total_hours": round(sum(rules.hours_between(a.check_in, a.check_out) for a in records), 1)})
    return jsonify(user_id=target, year=year, months=months)
