import functools

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .models import User, db


def hash_password(password):
    # PBKDF2 rather than Werkzeug's scrypt default: scrypt is missing from some Python builds (e.g. macOS system Python)
    return generate_password_hash(password, method="pbkdf2:sha256")


def current_user():
    uid = session.get("uid")
    user = db.session.get(User, uid) if uid else None
    return user if user and user.active else None


def api_auth(*roles):
    """JSON endpoints: 401 when logged out, 403 when the role is not allowed (no roles = any logged-in user)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if user is None:
                return jsonify(error="Login required"), 401
            if roles and user.role not in roles:
                return jsonify(error="You do not have permission to do this"), 403
            return fn(user, *a, **kw)
        return wrapper
    return deco


def page_auth(*roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if user is None:
                return redirect(url_for("pages.login"))
            if roles and user.role not in roles:
                return redirect(url_for("pages.dashboard"))
            return fn(user, *a, **kw)
        return wrapper
    return deco


def authenticate(email, password):
    user = User.query.filter(db.func.lower(User.email) == (email or "").strip().lower()).first()
    return user if user and user.active and check_password_hash(user.password_hash, password or "") else None
