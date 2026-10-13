"""Demo data: fictional people, departments, leave types, holidays and ~2 months of attendance history."""
import random
from datetime import date, datetime, time, timedelta

from . import rules
from .auth import hash_password
from .models import (ADMIN, APPROVED, CANCELLED, EMPLOYEE, MANAGER, PENDING, REJECTED, Attendance, Department, Holiday,
                     LeaveRequest, LeaveType, User, db)

DEMO_PASSWORD = "demo1234"


def seed_reference_data(today):
    for name, days, back in (("Annual", 20, False), ("Sick", 10, True), ("Personal", 3, False), ("Unpaid", None, False)):
        db.session.add(LeaveType(name=name, annual_days=days, allow_backdate=back))
    for y in (today.year - 1, today.year, today.year + 1):
        for (m, d), name in {(1, 1): "New Year's Day", (5, 1): "Labour Day", (12, 25): "Christmas Day",
                             (12, 26): "Boxing Day"}.items():
            db.session.add(Holiday(date=date(y, m, d), name=name))
    for name in ("Engineering", "Sales", "People & Finance"):
        db.session.add(Department(name=name))
    db.session.commit()


def seed_people(today):
    """Departments' staff (admin, two managers, eight employees). Returns (admin, m_eng, m_sales, team)."""
    dept = {d.name: d.id for d in Department.query}
    pw = hash_password(DEMO_PASSWORD)

    def add(name, email, role, department, manager=None):
        u = User(name=name, email=email, password_hash=pw, role=role, department_id=dept[department],
                 manager_id=manager.id if manager else None, hire_date=today - timedelta(days=400))
        db.session.add(u)
        db.session.flush()
        return u

    admin = add("Hana Admin", "admin@example.test", ADMIN, "People & Finance")
    m_eng = add("Morgan Lee", "morgan@example.test", MANAGER, "Engineering", admin)
    m_sales = add("Sasha Patel", "sasha@example.test", MANAGER, "Sales", admin)
    team = [add(n, e, EMPLOYEE, "Engineering", m_eng) for n, e in (
        ("Alex Rivera", "alex@example.test"), ("Jordan Blake", "jordan@example.test"),
        ("Casey Moreno", "casey@example.test"), ("Riley Okonkwo", "riley@example.test"))]
    team += [add(n, e, EMPLOYEE, "Sales", m_sales) for n, e in (
        ("Taylor Lindqvist", "taylor@example.test"), ("Jamie Haddad", "jamie@example.test"),
        ("Drew Novak", "drew@example.test"))]
    team.append(add("Quinn Abara", "quinn@example.test", EMPLOYEE, "People & Finance", admin))
    db.session.commit()
    return admin, m_eng, m_sales, team


def seed_demo(today):
    seed_reference_data(today)
    admin, m_eng, m_sales, team = seed_people(today)

    # approved leave first so attendance generation can skip those days
    types = {t.name: t for t in LeaveType.query}
    rnd = random.Random(7)

    def leave(user, kind, start, length, status, reviewer=None, comment=None):
        end = start + timedelta(days=length - 1)
        days = rules.business_days(start, end, rules.holidays_between(start, end))
        if days:
            db.session.add(LeaveRequest(user_id=user.id, leave_type_id=types[kind].id, start_date=start, end_date=end,
                                        days=days, reason="Demo request", status=status,
                                        reviewer_id=reviewer.id if reviewer else None, review_comment=comment,
                                        decided_at=datetime.utcnow() if reviewer else None))

    monday = today - timedelta(days=today.weekday())   # every offset below is a multiple of 7 so requests start on weekdays
    leave(team[0], "Annual", monday - timedelta(days=21), 5, APPROVED, m_eng)
    leave(team[1], "Sick", monday - timedelta(days=7), 2, APPROVED, m_eng)
    leave(team[4], "Annual", monday - timedelta(days=14), 3, APPROVED, m_sales)
    leave(team[5], "Personal", monday - timedelta(days=28), 1, REJECTED, m_sales, "Month-end close, please pick another day")
    leave(team[2], "Annual", monday + timedelta(days=14), 4, PENDING)
    leave(team[3], "Annual", monday + timedelta(days=21), 5, PENDING)
    leave(team[6], "Personal", monday + timedelta(days=7), 1, PENDING)
    leave(team[7], "Annual", monday + timedelta(days=28), 3, CANCELLED)
    db.session.commit()

    holidays = rules.holidays_between(today - timedelta(days=70), today)
    approved = LeaveRequest.query.filter_by(status=APPROVED).all()
    everyone = [admin, m_eng, m_sales] + team
    for offset in range(70, -1, -1):
        d = today - timedelta(days=offset)
        if d.weekday() >= 5 or d in holidays:
            continue
        for u in everyone:
            if any(r.user_id == u.id and r.start_date <= d <= r.end_date for r in approved):
                continue
            if d == today and rnd.random() < 0.4:
                continue                                   # some people have not arrived yet today
            roll = rnd.random()
            if roll < 0.04:
                continue                                   # unexplained absence
            late = rnd.random() < 0.12
            start = time(9, rnd.randint(16, 50)) if late else time(8, rnd.randint(35, 59))
            out = None if d == today else time(17, rnd.randint(0, 45)) if roll > 0.1 else time(13, rnd.randint(0, 30))
            status = "remote" if rnd.random() < 0.15 else "half_day" if out and out < time(14) else "present"
            db.session.add(Attendance(user_id=u.id, date=d, check_in=start, check_out=out, status=status))
    db.session.commit()
