import re

import pytest

from app import DEFAULT_WINDOWS, create_app
from app.models import Market, Outcome, User, db


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "t",
                      "WTF_CSRF_ENABLED": False})
    with app.app_context():
        for name, admin in (("alice", True), ("bob", False), ("carol", False)):
            u = User(username=name, display_name=name.title(), is_admin=admin, cash=1000.0)
            u.set_password("secret1")
            db.session.add(u)
        db.session.flush()
        for u in User.query.all():
            m = Market(subject_id=u.id, question=f"When will {u.display_name} get married?", b=250.0)
            db.session.add(m)
            db.session.flush()
            for i, l in enumerate(DEFAULT_WINDOWS):
                db.session.add(Outcome(market_id=m.id, label=l, sort_order=i))
        db.session.commit()
        yield app


@pytest.fixture
def users(app):
    return {u.username: u for u in User.query.all()}


def market_of(name):
    u = User.query.filter_by(username=name).first()
    return Market.query.filter_by(subject_id=u.id).first()
