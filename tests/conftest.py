import pytest

from app import create_app, markets, ratelimit
from app.models import User, db


@pytest.fixture
def app():
    ratelimit.reset_all()
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "t",
                      "WTF_CSRF_ENABLED": False, "GROUP_NAME": "Test Group"})
    with app.app_context():
        for name, admin in (("alice", True), ("bob", False), ("carol", False)):
            u = User(username=name, display_name=name.title(), is_admin=admin, cash=1000.0)
            u.set_password("secret123")
            db.session.add(u)
        db.session.commit()
        yield app


@pytest.fixture
def users(app):
    return {u.username: u for u in User.query.all()}


@pytest.fixture
def make_market(app, users):
    """make_market(creator='alice', kind='multiple_choice', n=4, **kw) -> Market"""
    def _make(creator="alice", kind="multiple_choice", labels=None, title="Who wins?", **kw):
        if kind == "multiple_choice":
            labels = labels or ["A", "B", "C", "D"]
            pairs = [(l, None) for l in labels]
        else:
            pairs = markets.parse_options(kind, None, start_year=2027, years=2)
        return markets.create_market(users[creator], title, kind, pairs, **kw)
    return _make


def login(client, name, pw="secret123"):
    return client.post("/login", data={"username": name, "password": pw})


def oid(market, label):
    return next(o.id for o in market.outcomes if o.label == label)
