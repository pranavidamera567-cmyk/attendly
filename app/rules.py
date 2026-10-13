"""Business rules: working days, leave balances, lateness, visibility of other people's records."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_

from .models import ADMIN, APPROVED, MANAGER, PENDING, Holiday, LeaveRequest, LeaveType, User, db

LATE_AFTER = time(9, 15)       # 09:00 start + 15 min grace


def holidays_between(start, end):
    return {h.date for h in Holiday.query.filter(Holiday.date >= start, Holiday.date <= end)}


def business_days(start, end, holidays):
    """Mon–Fri days in [start, end] that are not public holidays."""
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            n += 1
        d += timedelta(days=1)
    return n


def is_working_day(d):
    return d.weekday() < 5 and not holidays_between(d, d)


def month_bounds(year, month):
    first = date(year, month, 1)
    return first, (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))


def hours_between(check_in, check_out):
    if not check_in or not check_out:
        return 0.0
    a, b = datetime.combine(date.min, check_in), datetime.combine(date.min, check_out)
    return round((b - a).total_seconds() / 3600, 2)


def is_late(check_in):
    return bool(check_in and check_in > LATE_AFTER)


def leave_balances(user_id, year):
    """Per leave type: allowance, approved days, pending days (reserved) and what remains."""
    rows = []
    for lt in LeaveType.query.order_by(LeaveType.id):
        reqs = LeaveRequest.query.filter(LeaveRequest.user_id == user_id, LeaveRequest.leave_type_id == lt.id,
                                         LeaveRequest.start_date >= date(year, 1, 1),
                                         LeaveRequest.start_date <= date(year, 12, 31)).all()
        used = sum(r.days for r in reqs if r.status == APPROVED)
        pending = sum(r.days for r in reqs if r.status == PENDING)
        rows.append({"leave_type_id": lt.id, "leave_type": lt.name, "allowance": lt.annual_days, "used": used,
                     "pending": pending,
                     "remaining": None if lt.annual_days is None else lt.annual_days - used - pending})
    return rows


def visible_users(actor):
    """Query of the users `actor` may see records for: everyone (admin), the team plus self (manager), or self."""
    q = User.query.filter(User.active.is_(True))
    if actor.role == ADMIN:
        return q
    if actor.role == MANAGER:
        return q.filter(or_(User.manager_id == actor.id, User.id == actor.id))
    return q.filter(User.id == actor.id)


def can_view_user(actor, user_id):
    return visible_users(actor).filter(User.id == user_id).first() is not None


def approved_leave_on(user_id, d):
    return LeaveRequest.query.filter(LeaveRequest.user_id == user_id, LeaveRequest.status == APPROVED,
                                     LeaveRequest.start_date <= d, LeaveRequest.end_date >= d).first() is not None
