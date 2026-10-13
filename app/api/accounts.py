from datetime import date

from flask import Blueprint, jsonify, request, session
from ..auth import api_auth, authenticate, hash_password
from ..models import ADMIN, EMPLOYEE, MANAGER, ROLES, Department, User, db
from ..util import bad, commit, parse_date

bp = Blueprint("accounts", __name__, url_prefix="/api")


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    user = authenticate(body.get("email"), body.get("password"))
    if user is None:
        return bad("Invalid email or password", 401)
    session.clear()
    session["uid"] = user.id
    return jsonify(user.to_dict())


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/me")
@api_auth()
def me(user):
    return jsonify(user.to_dict())


@bp.get("/departments")
@api_auth()
def departments(user):
    return jsonify([{"id": d.id, "name": d.name} for d in Department.query.order_by(Department.name)])


@bp.get("/users")
@api_auth(MANAGER, ADMIN)
def users(user):
    from ..rules import visible_users
    q = visible_users(user) if user.role != ADMIN else User.query
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term.lower()}%"
        q = q.filter(db.or_(db.func.lower(User.name).like(like), db.func.lower(User.email).like(like)))
    if request.args.get("department_id", type=int):
        q = q.filter(User.department_id == request.args.get("department_id", type=int))
    return jsonify([u.to_dict() for u in q.order_by(User.name)])


@bp.post("/users")
@api_auth(ADMIN)
def create_user(admin):
    b = request.get_json(silent=True) or {}
    name, email, password = (b.get("name") or "").strip(), (b.get("email") or "").strip().lower(), b.get("password") or ""
    if not name or "@" not in email:
        return bad("A name and a valid email are required")
    if len(password) < 8:
        return bad("Password must be at least 8 characters")
    if b.get("role") not in ROLES:
        return bad(f"role must be one of {', '.join(ROLES)}")
    if db.session.get(Department, b.get("department_id")) is None:
        return bad("Unknown department")
    manager_id = b.get("manager_id")
    if manager_id is not None:
        manager = db.session.get(User, manager_id)
        if manager is None or manager.role not in (MANAGER, ADMIN):
            return bad("manager_id must refer to a manager or admin")
    if User.query.filter(db.func.lower(User.email) == email).first():
        return bad("That email is already registered", 409)
    try:
        hire = parse_date(b["hire_date"], "hire_date") if b.get("hire_date") else date.today()
    except ValueError as e:
        return bad(str(e))
    user = User(name=name, email=email, password_hash=hash_password(password), role=b["role"],
                department_id=b["department_id"], manager_id=manager_id, hire_date=hire)
    db.session.add(user)
    commit()
    return jsonify(user.to_dict()), 201


@bp.post("/users/<int:user_id>/deactivate")
@api_auth(ADMIN)
def deactivate(admin, user_id):
    target = db.session.get(User, user_id)
    if target is None:
        return bad("User not found", 404)
    if target.id == admin.id:
        return bad("You cannot deactivate your own account", 409)
    target.active = False
    commit()
    return jsonify(target.to_dict())
