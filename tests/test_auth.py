import pytest

from app import create_app
from app.models import User, db
from tests.conftest import market_of


def login(client, name, pw="secret1"):
    return client.post("/login", data={"username": name, "password": pw})


def test_login_required(app):
    c = app.test_client()
    for url in ("/profile", "/admin/", "/api/market/1/preview?outcome=1&dollars=5"):
        r = c.get(url)
        assert r.status_code == 302 and "/login" in r.location


def test_login_and_wrong_password(app):
    c = app.test_client()
    assert login(c, "bob", "nope").status_code == 200
    assert login(c, "bob").status_code == 302
    assert c.get("/").status_code == 200


def test_open_redirect_blocked(app):
    c = app.test_client()
    r = c.post("/login?next=//evil.com", data={"username": "bob", "password": "secret1"})
    assert "evil.com" not in r.location


def test_admin_only(app):
    c = app.test_client()
    login(c, "bob")
    assert c.get("/admin/").status_code == 403
    assert c.post("/admin/outcome/1/eliminate").status_code == 403
    c2 = app.test_client()
    login(c2, "alice")
    assert c2.get("/admin/").status_code == 200


def test_csrf_enforced():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "t"})
    with app.app_context():
        u = User(username="x", display_name="X", cash=1000)
        u.set_password("secret1")
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    assert c.post("/login", data={"username": "x", "password": "secret1"}).status_code == 400


def test_buy_via_http_and_pages(app):
    c = app.test_client()
    login(c, "bob")
    m = market_of("alice")
    oid = m.outcomes[1].id
    r = c.post(f"/market/{m.id}/buy", data={"outcome": oid, "dollars": "50"}, follow_redirects=True)
    assert b"Bought" in r.data
    assert c.get(f"/market/{m.id}").status_code == 200
    assert c.get(f"/api/market/{m.id}/history").json["points"]
    assert c.get(f"/api/market/{m.id}/preview?outcome={oid}&dollars=10").json["shares"] > 10
    assert c.get("/profile").status_code == 200
    assert c.get("/leaderboard").status_code == 200
    r = c.post(f"/market/{m.id}/sell", data={"outcome": oid, "shares": "all"}, follow_redirects=True)
    assert b"Sold" in r.data
    own = market_of("bob")
    r = c.post(f"/market/{own.id}/buy", data={"outcome": own.outcomes[0].id, "dollars": "5"}, follow_redirects=True)
    assert b"own market" in r.data


def test_public_pages_visible_without_login(app):
    c = app.test_client()
    m = market_of("alice")
    for url in ("/", f"/market/{m.id}", "/leaderboard", "/profile/1", "/api/leaderboard",
                f"/api/market/{m.id}/history"):
        assert c.get(url).status_code == 200, url
    assert b"Log in to bet" in c.get(f"/market/{m.id}").data
    assert b"name=\"dollars\"" not in c.get(f"/market/{m.id}").data


def test_betting_still_requires_login(app):
    c = app.test_client()
    m = market_of("alice")
    r = c.post(f"/market/{m.id}/buy", data={"outcome": m.outcomes[0].id, "dollars": "5"})
    assert r.status_code == 302 and "/login" in r.location


def test_login_returns_to_market(app):
    c = app.test_client()
    m = market_of("alice")
    r = c.post(f"/login?next=/market/{m.id}", data={"username": "bob", "password": "secret1"})
    assert r.location.endswith(f"/market/{m.id}")
