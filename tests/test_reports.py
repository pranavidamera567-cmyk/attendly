from datetime import date, time

from app.models import APPROVED, Attendance, LeaveRequest, LeaveType, User, db


def attend(uid, day, cin, cout, status="present"):
    db.session.add(Attendance(user_id=uid, date=date(2030, 3, day), check_in=time.fromisoformat(cin),
                              check_out=time.fromisoformat(cout) if cout else None, status=status))


def build(app):
    """Alex (id 4): 9 working days so far in March 2030 (1, 4-8, 11-13).
    6 full days + 1 half day attended, 1 of them late, 2 days of approved leave (11, 12)."""
    with app.app_context():
        for day, cin in ((1, "08:55"), (4, "09:00"), (5, "09:30"), (6, "08:45"), (7, "09:05"), (8, "08:50")):
            attend(4, day, cin, "17:00")
        attend(4, 13, "09:00", "13:00", "half_day")
        annual = LeaveType.query.filter_by(name="Annual").one()
        db.session.add(LeaveRequest(user_id=4, leave_type_id=annual.id, start_date=date(2030, 3, 11),
                                    end_date=date(2030, 3, 12), days=2, status=APPROVED, reason="=HYPERLINK(\"x\")"))
        for day in (1, 4, 5, 6, 7, 8, 11, 12, 13):      # Jordan (id 5) was there every day, never late
            attend(5, day, "08:50", "16:50")
        attend(8, 5, "09:00", "17:00")                  # Taylor (Sales, id 8): a single day
        db.session.commit()


def test_attendance_summary_numbers(app, as_user):
    build(app)
    admin = as_user("admin@example.test")
    rows = {r["employee"]: r for r in admin.get("/api/reports/attendance-summary?month=2030-03").json}
    alex = rows["Alex Rivera"]
    assert alex["expected_days"] == 9 and alex["present_days"] == 6 and alex["half_days"] == 1
    assert alex["leave_days"] == 2 and alex["absent_days"] == 0.5          # due 7, attended 6.5
    assert alex["attendance_rate"] == 92.9


def test_late_threshold_is_after_the_grace_period(app, as_user):
    build(app)
    rows = {r["employee"]: r for r in as_user("admin@example.test").get("/api/reports/attendance-summary?month=2030-03").json}
    assert rows["Alex Rivera"]["late_count"] == 1                            # only 09:30; 09:05 is within grace
    assert rows["Jordan Blake"]["late_count"] == 0
    assert rows["Jordan Blake"]["absent_days"] == 0 and rows["Jordan Blake"]["attendance_rate"] == 100.0
    assert rows["Jordan Blake"]["total_hours"] == 72.0
    assert rows["Casey Moreno"]["present_days"] == 0 and rows["Casey Moreno"]["absent_days"] == 9.0


def test_department_summary_aggregates_employees(app, as_user):
    build(app)
    depts = {d["department"]: d for d in as_user("admin@example.test").get("/api/reports/department-summary?month=2030-03").json}
    eng = depts["Engineering"]
    assert eng["headcount"] == 5 and eng["expected_days"] == 45 and eng["leave_days"] == 2   # 4 engineers + their manager
    assert eng["attended_days"] == 6.5 + 9                                   # alex + jordan
    assert eng["attendance_rate"] == round(100 * 15.5 / 43, 1)
    assert depts["Sales"]["headcount"] == 4 and depts["Sales"]["attended_days"] == 1
    only_sales = as_user("admin@example.test").get("/api/reports/department-summary?month=2030-03&department_id=2").json
    assert [d["department"] for d in only_sales] == ["Sales"]


def test_report_scoping_and_filters(app, as_user):
    build(app)
    morgan = as_user("morgan@example.test")
    names = {r["employee"] for r in morgan.get("/api/reports/attendance-summary?month=2030-03").json}
    assert {"Alex Rivera", "Jordan Blake", "Morgan Lee"} <= names and "Taylor Lindqvist" not in names
    assert [r["employee"] for r in as_user("admin@example.test").get("/api/reports/attendance-summary?month=2030-03&q=casey").json] == ["Casey Moreno"]
    assert as_user("alex@example.test").get("/api/reports/attendance-summary").status_code == 403
    assert as_user("admin@example.test").get("/api/reports/attendance-summary?month=bad").status_code == 400
    future = as_user("admin@example.test").get("/api/reports/attendance-summary?month=2030-05").json
    assert all(r["expected_days"] == 0 and r["attendance_rate"] is None for r in future)


def test_csv_exports(app, as_user):
    build(app)
    admin = as_user("admin@example.test")
    csv = admin.get("/api/reports/attendance-summary.csv?month=2030-03").get_data(as_text=True).splitlines()
    assert csv[0] == "employee,department,expected_days,present_days,half_days,leave_days,absent_days,late_count,total_hours,attendance_rate"
    assert any(line.startswith("Alex Rivera,Engineering,9,6,1,2,0.5,1,") for line in csv)
    res = admin.get("/api/reports/department-summary.csv?month=2030-03")
    assert res.mimetype == "text/csv" and "attachment" in res.headers["Content-Disposition"]
    leave_csv = admin.get("/api/reports/leave-requests.csv").get_data(as_text=True)
    assert "'=HYPERLINK" in leave_csv and ",=HYPERLINK" not in leave_csv      # formula injection neutralised
    assert as_user("alex@example.test").get("/api/reports/leave-requests.csv").status_code == 403


def test_employee_monthly_history(app, as_user):
    build(app)
    data = as_user("alex@example.test").get("/api/reports/employee-monthly?year=2030").json
    assert [m["month"] for m in data["months"]] == ["2030-01", "2030-02", "2030-03"]   # nothing after 'today'
    march = data["months"][-1]
    assert march["attended_days"] == 6.5 and march["leave_days"] == 2 and march["late_count"] == 1
    assert as_user("alex@example.test").get("/api/reports/employee-monthly?user_id=5").status_code == 403
    assert as_user("morgan@example.test").get("/api/reports/employee-monthly?user_id=5").status_code == 200


def test_demo_dataset_loads_and_reports(demo_app):
    from conftest import Client
    admin = Client(demo_app)
    assert admin.login("admin@example.test").status_code == 200
    rows = admin.get("/api/reports/attendance-summary?month=2030-03").json
    assert len(rows) == 11 and any(r["present_days"] > 0 for r in rows)
    assert admin.get("/api/leave/requests?per_page=100").json["total"] == 8
    pending = admin.get("/api/leave/requests?status=pending").json["total"]
    assert pending == 3
