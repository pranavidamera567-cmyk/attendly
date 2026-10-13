from datetime import date


# 2030-03-13 is a Wednesday; demo users: alex/jordan/casey/riley (Engineering, manager morgan), taylor (Sales, sasha)

def test_login_logout_and_csrf_header(app, as_user):
    anon = app.test_client()
    assert anon.get("/api/me").status_code == 401
    assert anon.post("/api/login", json={"email": "alex@example.test", "password": "demo1234"}).status_code == 400  # no header
    alex = as_user("alex@example.test")
    assert alex.get("/api/me").json["role"] == "employee"
    bad = app.test_client().post("/api/login", json={"email": "alex@example.test", "password": "nope"},
                                 headers={"X-Requested-With": "fetch"})
    assert bad.status_code == 401
    assert alex.post("/api/logout").status_code == 200
    assert alex.get("/api/me").status_code == 401


def test_leave_request_counts_working_days_and_validates(as_user):
    alex = as_user("alex@example.test")
    types = {t["name"]: t for t in alex.get("/api/leave/types").json}
    annual = types["Annual"]["id"]
    # Fri 15th .. Tue 19th: Fri, Mon, Tue = 3 working days (weekend excluded)
    r = alex.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-03-15", "end_date": "2030-03-19", "reason": "Trip"})
    assert r.status_code == 201 and r.json["days"] == 3 and r.json["status"] == "pending"
    bal = {b["leave_type"]: b for b in alex.get("/api/leave/balances?year=2030").json["balances"]}
    assert bal["Annual"]["pending"] == 3 and bal["Annual"]["remaining"] == 17

    post = lambda **kw: alex.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-04-01", "end_date": "2030-04-01", **kw})
    assert post(start_date="2030-03-16", end_date="2030-03-17").status_code == 400      # weekend only
    assert post(start_date="2030-03-18", end_date="2030-03-20").status_code == 409      # overlaps pending request
    assert post(start_date="2030-03-12", end_date="2030-03-12").status_code == 400      # in the past
    assert post(start_date="2030-04-05", end_date="2030-04-01").status_code == 400      # end before start
    assert post(start_date="2030-12-30", end_date="2031-01-02").status_code == 400      # spans two years
    assert post(start_date="nonsense").status_code == 400
    assert post(start_date="2030-05-01", end_date="2030-05-31").status_code == 409      # Labour Day excluded; 21 days > 17 left
    assert alex.post("/api/leave/requests", {"leave_type_id": 999, "start_date": "2030-04-01", "end_date": "2030-04-01"}).status_code == 400


def test_holiday_is_not_counted_and_sick_leave_can_be_backdated(as_user):
    alex = as_user("alex@example.test")
    types = {t["name"]: t["id"] for t in alex.get("/api/leave/types").json}
    r = alex.post("/api/leave/requests", {"leave_type_id": types["Annual"], "start_date": "2030-04-29", "end_date": "2030-05-03"})
    assert r.json["days"] == 4                                                           # Wed May 1 is Labour Day
    sick = alex.post("/api/leave/requests", {"leave_type_id": types["Sick"], "start_date": "2030-03-11", "end_date": "2030-03-12"})
    assert sick.status_code == 201 and sick.json["days"] == 2
    too_old = alex.post("/api/leave/requests", {"leave_type_id": types["Sick"], "start_date": "2030-02-01", "end_date": "2030-02-01"})
    assert too_old.status_code == 400
    unpaid = alex.post("/api/leave/requests", {"leave_type_id": types["Unpaid"], "start_date": "2030-06-03", "end_date": "2030-06-28"})
    assert unpaid.status_code == 201                                                     # no cap on unpaid leave


def test_approval_workflow_and_permissions(as_user):
    alex, jordan = as_user("alex@example.test"), as_user("jordan@example.test")
    morgan, sasha, admin = as_user("morgan@example.test"), as_user("sasha@example.test"), as_user("admin@example.test")
    annual = alex.get("/api/leave/types").json[0]["id"]
    rid = alex.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-04-08", "end_date": "2030-04-10"}).json["id"]
    other = jordan.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-04-08", "end_date": "2030-04-08"}).json["id"]

    assert jordan.post(f"/api/leave/requests/{rid}/approve").status_code == 403         # employees cannot review
    assert sasha.post(f"/api/leave/requests/{rid}/approve").status_code == 403          # wrong team's manager
    assert morgan.post(f"/api/leave/requests/{rid}/reject").status_code == 400          # comment required
    assert morgan.post(f"/api/leave/requests/{rid}/reject", {"comment": "Release week"}).json["status"] == "rejected"
    assert morgan.post(f"/api/leave/requests/{rid}/approve").status_code == 409         # already decided
    bal = {b["leave_type"]: b for b in alex.get("/api/leave/balances?year=2030").json["balances"]}
    assert bal["Annual"]["used"] == 0 and bal["Annual"]["pending"] == 0                 # rejection releases the days

    again = alex.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-04-08", "end_date": "2030-04-10"}).json["id"]
    approved = morgan.post(f"/api/leave/requests/{again}/approve", {"comment": "Enjoy"}).json
    assert approved["status"] == "approved" and approved["reviewer"] == "Morgan Lee"
    bal = {b["leave_type"]: b for b in alex.get("/api/leave/balances?year=2030").json["balances"]}
    assert bal["Annual"]["used"] == 3 and bal["Annual"]["remaining"] == 17

    assert admin.post(f"/api/leave/requests/{other}/approve").json["status"] == "approved"   # admin can review anyone
    mine = morgan.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-05-06", "end_date": "2030-05-06"}).json["id"]
    assert morgan.post(f"/api/leave/requests/{mine}/approve").status_code == 403         # nobody approves their own
    assert admin.post(f"/api/leave/requests/{mine}/approve").status_code == 200

    # approved future leave can be cancelled, which gives the days back
    assert alex.post(f"/api/leave/requests/{again}/cancel").json["status"] == "cancelled"
    bal = {b["leave_type"]: b for b in alex.get("/api/leave/balances?year=2030").json["balances"]}
    assert bal["Annual"]["remaining"] == 20
    assert alex.post(f"/api/leave/requests/{again}/cancel").status_code == 409
    assert jordan.post(f"/api/leave/requests/{again}/cancel").status_code == 404         # not theirs


def test_leave_listing_scopes_search_and_filters(as_user):
    alex, jordan, taylor = as_user("alex@example.test"), as_user("jordan@example.test"), as_user("taylor@example.test")
    morgan, admin = as_user("morgan@example.test"), as_user("admin@example.test")
    annual = alex.get("/api/leave/types").json[0]["id"]
    alex.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-04-08", "end_date": "2030-04-08"})
    taylor.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-04-09", "end_date": "2030-04-09"})

    names = lambda c, qs="": {r["employee"] for r in c.get(f"/api/leave/requests?{qs}").json["items"]}
    assert "Taylor Lindqvist" not in names(alex) and names(jordan) == set() | {r for r in names(jordan)} and "Alex Rivera" not in names(jordan)
    team = names(morgan)
    assert "Alex Rivera" in team and "Taylor Lindqvist" not in team                     # manager sees only their team
    assert {"Alex Rivera", "Taylor Lindqvist"} <= names(admin)
    assert names(admin, "q=taylor&status=pending") == {"Taylor Lindqvist"}
    assert names(admin, "q=zzzz") == set()
    assert "Taylor Lindqvist" not in names(admin, "department_id=1") and "Alex Rivera" in names(admin, "department_id=1")
    page = admin.get("/api/leave/requests?per_page=1&page=1").json
    assert len(page["items"]) == 1 and page["pages"] == page["total"] and page["total"] >= 2
    assert admin.get("/api/leave/requests?from=bad").status_code == 400


def test_attendance_check_in_out_and_lateness(as_user, clock):
    from datetime import datetime
    alex = as_user("alex@example.test")
    clock.value = datetime(2030, 3, 13, 9, 40)
    rec = alex.post("/api/attendance/check-in").json
    assert rec["check_in"] == "09:40" and rec["late"] is True
    assert alex.post("/api/attendance/check-in").status_code == 409
    clock.value = datetime(2030, 3, 13, 17, 10)
    out = alex.post("/api/attendance/check-out").json
    assert out["hours"] == 7.5 and out["check_out"] == "17:10"
    assert alex.post("/api/attendance/check-out").status_code == 409
    assert alex.get("/api/attendance/today").json["id"] == rec["id"]
    assert as_user("jordan@example.test").post("/api/attendance/check-out").status_code == 409   # never checked in


def test_manual_attendance_rules(as_user, clock):
    alex, admin = as_user("alex@example.test"), as_user("admin@example.test")
    entry = {"date": "2030-03-12", "check_in": "08:50", "check_out": "17:00", "status": "present", "note": "forgot to check in"}
    created = alex.post("/api/attendance", entry)
    assert created.status_code == 201 and created.json["hours"] == 8.17 and created.json["late"] is False
    assert alex.post("/api/attendance", entry).status_code == 409                       # one record per day
    assert alex.post("/api/attendance", {**entry, "date": "2030-03-14"}).status_code == 400   # future
    assert alex.post("/api/attendance", {**entry, "date": "2030-03-09"}).status_code == 409   # Saturday
    assert alex.post("/api/attendance", {**entry, "date": "2030-03-04"}).status_code == 403   # older than 7 days
    assert alex.post("/api/attendance", {**entry, "date": "2030-03-11", "check_out": "08:00"}).status_code == 400
    assert alex.post("/api/attendance", {**entry, "date": "2030-03-11", "status": "party"}).status_code == 400
    assert alex.post("/api/attendance", {**entry, "date": "2030-03-11", "user_id": 3}).status_code == 403  # someone else
    # admin may back-fill any employee any time
    assert admin.post("/api/attendance", {**entry, "date": "2030-03-04", "user_id": created.json["user_id"]}).status_code == 201
    # editing
    upd = alex.put(f"/api/attendance/{created.json['id']}", {"check_out": "12:00", "status": "half_day"})
    assert upd.status_code == 200 and upd.json["hours"] == 3.17 and upd.json["status"] == "half_day"
    assert as_user("jordan@example.test").put(f"/api/attendance/{created.json['id']}", {}).status_code == 404


def test_cannot_clock_in_on_approved_leave(as_user, clock):
    alex, morgan = as_user("alex@example.test"), as_user("morgan@example.test")
    annual = alex.get("/api/leave/types").json[0]["id"]
    rid = alex.post("/api/leave/requests", {"leave_type_id": annual, "start_date": "2030-03-13", "end_date": "2030-03-14"}).json["id"]
    morgan.post(f"/api/leave/requests/{rid}/approve")
    assert alex.post("/api/attendance/check-in").status_code == 409
    assert alex.post("/api/attendance", {"date": "2030-03-13", "check_in": "09:00"}).status_code == 409


def test_attendance_visibility(as_user):
    admin = as_user("admin@example.test")
    for who, uid in (("alex", 4), ("jordan", 5), ("taylor", 8)):
        admin.post("/api/attendance", {"date": "2030-03-12", "check_in": "09:00", "user_id": uid})
    rows = lambda c, qs="": {r["employee"] for r in c.get(f"/api/attendance?month=2030-03&{qs}").json["items"] if r["date"] == "2030-03-12"}
    assert rows(as_user("alex@example.test")) == {"Alex Rivera"}
    assert rows(as_user("morgan@example.test")) >= {"Alex Rivera", "Jordan Blake"} and "Taylor Lindqvist" not in rows(as_user("morgan@example.test"))
    assert {"Alex Rivera", "Taylor Lindqvist"} <= rows(admin) and rows(admin, "q=taylor") == {"Taylor Lindqvist"}
    assert as_user("alex@example.test").get("/api/leave/balances?user_id=5").status_code == 403
    assert as_user("morgan@example.test").get("/api/leave/balances?user_id=5").status_code == 200
    assert as_user("morgan@example.test").get("/api/leave/balances?user_id=8").status_code == 403
    assert admin.get("/api/attendance?month=2030-13").status_code == 400


def test_user_administration(app, as_user):
    admin, alex = as_user("admin@example.test"), as_user("alex@example.test")
    body = {"name": "New Hire", "email": "new@example.test", "password": "longenough1", "role": "employee",
            "department_id": 1, "manager_id": 2}
    assert alex.post("/api/users", body).status_code == 403
    assert admin.post("/api/users", {**body, "password": "short"}).status_code == 400
    assert admin.post("/api/users", {**body, "manager_id": 4}).status_code == 400        # manager must be a manager/admin
    created = admin.post("/api/users", body)
    assert created.status_code == 201 and created.json["manager"] == "Morgan Lee"
    assert admin.post("/api/users", body).status_code == 409
    fresh = Client_for(app)
    assert fresh.login("new@example.test", "longenough1").status_code == 200
    assert admin.post(f"/api/users/{created.json['id']}/deactivate").json["active"] is False
    assert Client_for(app).login("new@example.test", "longenough1").status_code == 401
    assert fresh.get("/api/me").status_code == 401                                        # existing sessions end too
    assert admin.post("/api/users/1/deactivate").status_code == 409                       # not yourself
    assert len(admin.get("/api/users?q=new@").json) == 1


def Client_for(app):
    from conftest import Client
    return Client(app)


def test_pages_and_role_gating(app, as_user):
    anon = app.test_client()
    assert anon.get("/login").status_code == 200
    assert anon.get("/").status_code == 302 and "/login" in anon.get("/").headers["Location"]
    alex = as_user("alex@example.test")
    assert alex.get("/").status_code == 200 and alex.get("/attendance").status_code == 200 and alex.get("/leave").status_code == 200
    assert alex.get("/reports").status_code == 302 and alex.get("/admin/users").status_code == 302
    assert alex.get("/api/reports/attendance-summary").status_code == 403
    assert as_user("morgan@example.test").get("/reports").status_code == 200
    assert as_user("morgan@example.test").get("/admin/users").status_code == 302
    assert as_user("admin@example.test").get("/admin/users").status_code == 200
