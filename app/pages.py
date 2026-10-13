from flask import Blueprint, redirect, render_template, url_for

from .auth import current_user, page_auth
from .models import ADMIN, MANAGER

bp = Blueprint("pages", __name__)


@bp.get("/login")
def login():
    if current_user():
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html")


@bp.get("/")
@page_auth()
def dashboard(user):
    return render_template("dashboard.html", user=user, page="dashboard")


@bp.get("/attendance")
@page_auth()
def attendance(user):
    return render_template("attendance.html", user=user, page="attendance")


@bp.get("/leave")
@page_auth()
def leave(user):
    return render_template("leave.html", user=user, page="leave")


@bp.get("/reports")
@page_auth(MANAGER, ADMIN)
def reports(user):
    return render_template("reports.html", user=user, page="reports")


@bp.get("/admin/users")
@page_auth(ADMIN)
def users(user):
    return render_template("users.html", user=user, page="users")
