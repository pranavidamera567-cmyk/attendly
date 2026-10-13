from datetime import datetime

import pytest

from app import create_app
from app.models import db

NOW = datetime(2030, 3, 13, 10, 0)   # a Wednesday, 10:00


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


class Client:
    """Test client that sends the CSRF header and JSON, and logs in by email."""

    def __init__(self, app):
        self.c = app.test_client()

    def login(self, email, password="demo1234"):
        return self.c.post("/api/login", json={"email": email, "password": password}, headers=self._h())

    @staticmethod
    def _h():
        return {"X-Requested-With": "fetch"}

    def get(self, url):
        return self.c.get(url)

    def post(self, url, json=None):
        return self.c.post(url, json={} if json is None else json, headers=self._h())

    def put(self, url, json=None):
        return self.c.put(url, json=json or {}, headers=self._h())


@pytest.fixture()
def clock():
    return Clock()


def make_app(tmp_path, clock, **extra):
    return create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 't.db'}", "NOW": clock, "SECRET_KEY": "test",
                       "TESTING": True, **extra})


@pytest.fixture()
def app(tmp_path, clock):
    """Reference data and people only (no history), so tests assert on exactly the records they create.

    Ids: 1 admin, 2 morgan (eng manager), 3 sasha (sales manager), 4-7 engineers alex/jordan/casey/riley,
    8-10 sales taylor/jamie/drew, 11 quinn (People & Finance)."""
    app = make_app(tmp_path, clock, SEED_DEMO_DATA=False)
    with app.app_context():
        from app.seed import seed_people, seed_reference_data
        seed_reference_data(NOW.date())
        seed_people(NOW.date())
    return app


@pytest.fixture()
def demo_app(tmp_path, clock):
    """The full demo dataset, seeded by create_app."""
    return make_app(tmp_path, clock)


@pytest.fixture()
def as_user(app):
    def make(email):
        c = Client(app)
        assert c.login(email).status_code == 200
        return c
    return make
