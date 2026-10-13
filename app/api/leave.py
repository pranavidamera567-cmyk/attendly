from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from .. import rules
from ..auth import api_auth
from ..models import (ADMIN, APPROVED, CANCELLED, MANAGER, PENDING, REJECTED, Holiday, LeaveRequest, LeaveType, User,
                      db)
from ..util import bad, commit, csv_response, paginate, parse_date

bp = Blueprint("leave", __name__, url_prefix="/api")


def today():
    return current_app.config["NOW"]().date()


@bp.get("/leave/types")
@api_auth()
def types(user):
    return jsonify([t.to_dict() for t in LeaveType.query.order_by(LeaveType.id)])


@bp.get("/holidays")
@api_auth()
def holidays(user):
    year = request.args.get("year", today().year, type=int)
    return jsonify([{"date": h.date.isoformat(), "name": h.name}
                    for h in Holiday.query.filter(db.extract("year", Holiday.date) == year).order_by(Holiday.date)])


@bp.get("/leave/balances")
@api_auth()
def balances(user):
    target = request.args.get("user_id", user.id, type=int)
    if not rules.can_view_user(user, target):
        return bad("You cannot view that employee's balances", 403)
    year = request.args.get("year", today().year, type=int)
    return jsonify(user_id=target, year=year, balances=rules.leave_balances(target, year))


@bp.post("/leave/requests")
@api_auth()
def create_request(user):
    b = request.get_json(silent=True) or {}
    try:
        start, end = parse_date(b.get("start_date"), "start_date"), parse_date(b.get("end_date"), "end_date")
    except ValueError as e:
        return bad(str(e))
    lt = db.session.get(LeaveType, b.get("leave_type_id"))
    if lt is None:
        return bad("Unknown leave type")
    if end < start:
        return bad("End date cannot be before the start date")
    if start.year != end.year:
        return bad("A request cannot span two calendar years; submit one request per year")
    now = today()
    if start < now and not (lt.allow_backdate and (now - start).days <= 14):
        return bad("Start date is in the past" + (" (back-dating is limited to 14 days for this leave type)"
                                                  if lt.allow_backdate else ""))
    days = rules.business_days(start, end, rules.holidays_between(start, end))
    if days == 0:
        return bad("The selected dates contain no working days")
    clash = LeaveRequest.query.filter(LeaveRequest.user_id == user.id, LeaveRequest.status.in_([PENDING, APPROVED]),
                                      LeaveRequest.start_date <= end, LeaveRequest.end_date >= start).first()
    if clash:
        return bad(f"Overlaps your {clash.status} request #{clash.id} ({clash.start_date} to {clash.end_date})", 409)
    balance = next(r for r in rules.leave_balances(user.id, start.year) if r["leave_type_id"] == lt.id)
    if balance["remaining"] is not None and days > balance["remaining"]:
        return bad(f"Not enough {lt.name} leave: {days} working days requested, {balance['remaining']} remaining", 409)
    req = LeaveRequest(user_id=user.id, leave_type_id=lt.id, start_date=start, end_date=end, days=days,
                       reason=(b.get("reason") or "").strip()[:500])
    db.session.add(req)
    commit()
    return jsonify(req.to_dict()), 201


def scoped_requests(user):
    """Leave requests the caller may see, filtered by the search parameters."""
    default = {"employee": "mine", "manager": "team", "admin": "all"}[user.role]
    scope = request.args.get("scope") or default
    q = LeaveRequest.query.join(User, LeaveRequest.user_id == User.id)
    if user.role == "employee" or scope == "mine":
        q = q.filter(LeaveRequest.user_id == user.id)
    elif scope == "team" or user.role == MANAGER:         # a manager never sees beyond their own team
        q = q.filter(User.manager_id == user.id)
    # admins asking for scope=all see everyone
    term = (request.args.get("q") or "").strip().lower()
    if term:
        q = q.filter(db.or_(db.func.lower(User.name).like(f"%{term}%"), db.func.lower(User.email).like(f"%{term}%")))
    if request.args.get("status"):
        q = q.filter(LeaveRequest.status == request.args["status"])
    if request.args.get("department_id", type=int):
        q = q.filter(User.department_id == request.args.get("department_id", type=int))
    if request.args.get("from"):
        q = q.filter(LeaveRequest.end_date >= parse_date(request.args["from"], "from"))
    if request.args.get("to"):
        q = q.filter(LeaveRequest.start_date <= parse_date(request.args["to"], "to"))
    return q.order_by(LeaveRequest.created_at.desc(), LeaveRequest.id.desc())


@bp.get("/leave/requests")
@api_auth()
def list_requests(user):
    try:
        return paginate(scoped_requests(user), lambda r: r.to_dict())
    except ValueError as e:
        return bad(str(e))


@bp.get("/reports/leave-requests.csv")
@api_auth(MANAGER, ADMIN)
def export_requests(user):
    try:
        rows = scoped_requests(user).all()
    except ValueError as e:
        return bad(str(e))
    return csv_response("leave-requests.csv",
                        ["id", "employee", "department", "leave_type", "start_date", "end_date", "working_days",
                         "status", "reviewer", "review_comment", "reason"],
                        [(r.id, r.user.name, r.user.department.name, r.leave_type.name, r.start_date, r.end_date, r.days,
                          r.status, r.reviewer.name if r.reviewer else "", r.review_comment or "", r.reason)
                         for r in rows])


def _decide(user, req_id, status):
    req = db.session.get(LeaveRequest, req_id)
    if req is None:
        return bad("Leave request not found", 404)
    if req.user_id == user.id:
        return bad("You cannot review your own request", 403)
    if user.role != ADMIN and req.user.manager_id != user.id:
        return bad("Only the employee's manager (or an admin) can review this request", 403)
    if req.status != PENDING:
        return bad(f"Request is already {req.status}", 409)
    comment = ((request.get_json(silent=True) or {}).get("comment") or "").strip()
    if status == REJECTED and not comment:
        return bad("A comment is required when rejecting a request")
    req.status, req.reviewer_id, req.review_comment = status, user.id, comment[:500] or None
    req.decided_at = datetime.utcnow()
    commit()
    return jsonify(req.to_dict())


@bp.post("/leave/requests/<int:req_id>/approve")
@api_auth(MANAGER, ADMIN)
def approve(user, req_id):
    return _decide(user, req_id, APPROVED)


@bp.post("/leave/requests/<int:req_id>/reject")
@api_auth(MANAGER, ADMIN)
def reject(user, req_id):
    return _decide(user, req_id, REJECTED)


@bp.post("/leave/requests/<int:req_id>/cancel")
@api_auth()
def cancel(user, req_id):
    req = db.session.get(LeaveRequest, req_id)
    if req is None or (req.user_id != user.id and user.role != ADMIN):
        return bad("Leave request not found", 404)
    if req.status == PENDING or (req.status == APPROVED and req.start_date > today()):
        req.status = CANCELLED
        commit()
        return jsonify(req.to_dict())
    return bad(f"A {req.status} request cannot be cancelled" +
               (" once it has started" if req.status == APPROVED else ""), 409)
