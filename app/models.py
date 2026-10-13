from datetime import date, datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

EMPLOYEE, MANAGER, ADMIN = "employee", "manager", "admin"
ROLES = (EMPLOYEE, MANAGER, ADMIN)
PENDING, APPROVED, REJECTED, CANCELLED = "pending", "approved", "rejected", "cancelled"
ATTENDANCE_STATUSES = ("present", "remote", "half_day")


class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default=EMPLOYEE)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False)
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    active = db.Column(db.Boolean, nullable=False, default=True)
    hire_date = db.Column(db.Date, nullable=False, default=date.today)

    department = db.relationship("Department")
    manager = db.relationship("User", remote_side=[id])

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role, "active": self.active,
                "department_id": self.department_id, "department": self.department.name,
                "manager_id": self.manager_id, "manager": self.manager.name if self.manager else None,
                "hire_date": self.hire_date.isoformat()}


class LeaveType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)
    annual_days = db.Column(db.Integer)                 # None = no cap (e.g. unpaid leave)
    allow_backdate = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "annual_days": self.annual_days, "allow_backdate": self.allow_backdate}


class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    leave_type_id = db.Column(db.Integer, db.ForeignKey("leave_type.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False)
    days = db.Column(db.Integer, nullable=False)        # working days, weekends and holidays excluded
    reason = db.Column(db.String(500), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default=PENDING, index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    review_comment = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])
    leave_type = db.relationship("LeaveType")

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "employee": self.user.name,
                "department": self.user.department.name, "leave_type": self.leave_type.name,
                "leave_type_id": self.leave_type_id, "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(), "days": self.days, "reason": self.reason,
                "status": self.status, "reviewer": self.reviewer.name if self.reviewer else None,
                "review_comment": self.review_comment, "created_at": self.created_at.strftime("%Y-%m-%d %H:%M"),
                "decided_at": self.decided_at.strftime("%Y-%m-%d %H:%M") if self.decided_at else None}


class Attendance(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_attendance_user_date"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.Time)
    check_out = db.Column(db.Time)
    status = db.Column(db.String(16), nullable=False, default="present")
    note = db.Column(db.String(200), nullable=False, default="")

    user = db.relationship("User")
