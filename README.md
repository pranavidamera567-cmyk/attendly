# attendly

Employee attendance and leave management portal (Sep 2021 – Jan 2022).

Employees record attendance and request leave; managers approve or reject their team's requests; administrators get
searchable tables, monthly summaries by employee and department, and export-ready reports. All records are stored in PostgreSQL.

**Stack:** Python, Flask, SQLAlchemy (Flask-SQLAlchemy), PostgreSQL, JavaScript, Bootstrap 5, pgAdmin

> **Demo data only** — every person and record is fictional. Demo accounts all use the password `demo1234`; change `SECRET_KEY`
> and remove the demo data (`SEED_DEMO_DATA=false`) for any real deployment.

## Roles
| Role | Can |
|---|---|
| Employee | check in/out, enter attendance (last 7 days), request / cancel leave, see own balances and history |
| Manager | everything above, plus approve / reject their direct reports' requests, see team attendance, leave and reports |
| Admin | everything, plus all employees' data, back-filling attendance, creating / deactivating users, CSV exports |

Demo logins: `alex@example.test` (employee), `morgan@example.test` (manager), `admin@example.test` (admin).

## Rules
- **Leave days** are working days: weekends and public holidays are excluded. A request cannot span two calendar years, cannot overlap
  another pending/approved request, cannot start in the past (sick leave may be back-dated up to 14 days) and cannot exceed the remaining balance.
- **Balances** per leave type and year = allowance − approved − pending (pending days are reserved; rejecting or cancelling releases them). Unpaid leave has no cap.
- **Workflow:** `pending → approved | rejected` by the employee's manager or an admin; nobody reviews their own request; rejection needs a comment.
  Employees can cancel pending requests and approved ones that have not started.
- **Attendance:** one record per working day; no entries for weekends, holidays, future dates or days covered by approved leave. Arrival after 09:15 counts as late.
- **Reports:** "expected" days are working days up to today (current month); attendance % = attended ÷ (expected − leave); half days count 0.5.

## Run
```bash
docker compose up --build
# app:     http://localhost:5002
# pgAdmin: http://localhost:5050   (admin@example.com / admin; the "attendly" server is pre-registered, DB password: attendly)
```
Without Docker (SQLite file; set `DATABASE_URL` for PostgreSQL):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python wsgi.py        # http://localhost:5002
```

## API (JSON, session cookie)
| | |
|---|---|
| `POST /api/login` · `/api/logout` · `GET /api/me` | session |
| `GET /api/leave/types` · `/api/holidays` · `/api/leave/balances?user_id=&year=` | reference data and balances |
| `POST /api/leave/requests` · `GET /api/leave/requests?q=&status=&department_id=&from=&to=&page=` | create / search |
| `POST /api/leave/requests/<id>/approve` · `/reject` · `/cancel` | workflow |
| `POST /api/attendance/check-in` · `/check-out` · `GET /api/attendance/today` | clock in/out |
| `POST /api/attendance` · `PUT /api/attendance/<id>` · `GET /api/attendance?month=&q=` | manual entry / search |
| `GET /api/reports/attendance-summary` · `/department-summary` · `/employee-monthly` (+ `.csv`) · `/leave-requests.csv` | reports (manager, admin) |
| `GET/POST /api/users` · `POST /api/users/<id>/deactivate` | user admin (admin) |

All data is scoped server-side by role. State-changing calls must send `X-Requested-With: fetch` (CSRF defence; the bundled JS does this).
CSV cells that start with `= + - @` are prefixed with `'` to prevent spreadsheet formula injection.

## Test
```bash
pytest
```
