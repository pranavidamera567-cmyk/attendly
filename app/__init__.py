import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .models import Department, db

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    (ROOT / "instance").mkdir(exist_ok=True)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'instance' / 'attendly.db'}"),
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SEED_DEMO_DATA=os.environ.get("SEED_DEMO_DATA", "true").lower() == "true",
        NOW=datetime.now,                      # tests replace this with a fixed clock
    )
    app.config.update(config or {})

    db.init_app(app)

    from .api import accounts, attendance, leave, reports
    from .pages import bp as pages
    for module in (accounts, attendance, leave, reports):
        app.register_blueprint(module.bp)
    app.register_blueprint(pages)

    with app.app_context():
        db.create_all()
        if app.config["SEED_DEMO_DATA"] and Department.query.first() is None:
            from .seed import seed_demo
            seed_demo(app.config["NOW"]().date())

    @app.before_request
    def require_ajax_header():
        """CSRF defence: browsers cannot add custom headers to cross-site form posts, and cross-site fetches with
        one need a CORS preflight that this app never grants. So every state-changing API call must carry it."""
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.path.startswith("/api/"):
            if request.headers.get("X-Requested-With") != "fetch":
                return jsonify(error="Missing X-Requested-With: fetch header"), 400

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    return app
