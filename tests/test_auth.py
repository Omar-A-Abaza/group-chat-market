import re
from datetime import timedelta

import pytest

from app import create_app, ratelimit
from app.models import Comment, Invite, Market, User, db, now
from tests.conftest import login, oid


# ---- access control ------------------------------------------------------------------------

def test_public_pages_visible_without_login(app, make_market):
    m = make_market()
    c = app.test_client()
    for url in ("/", f"/market/{m.id}", "/leaderboard", "/profile/1", "/api/leaderboard",
                f"/api/market/{m.id}/history", "/api/markets", "/login"):
        assert c.get(url).status_code == 200, url
    page = c.get(f"/market/{m.id}").data
    assert b"Log in to bet" in page and b'name="dollars"' not in page


def test_login_required_pages(app):
    c = app.test_client()
    for url in ("/profile", "/markets/new", "/admin/", "/profile/export.csv",
                "/api/market/1/preview?outcome=1&dollars=5"):
        r = c.get(url)
        assert r.status_code == 302 and "/login" in r.location, url


def test_betting_requires_login(app, make_market):
    m = make_market()
    r = app.test_client().post(f"/market/{m.id}/buy", data={"outcome": m.outcomes[0].id, "dollars": "5"})
    assert r.status_code == 302 and "/login" in r.location


def test_login_wrong_password_then_ok(app):
    c = app.test_client()
    assert b"Wrong username" in c.post("/login", data={"username": "bob", "password": "no"}).data
    assert login(c, "bob").status_code == 302
    assert c.get("/profile").status_code == 200


def test_login_returns_to_market_and_blocks_open_redirect(app, make_market):
    m = make_market()
    c = app.test_client()
    r = c.post(f"/login?next=/market/{m.id}", data={"username": "bob", "password": "secret123"})
    assert r.location.endswith(f"/market/{m.id}")
    r = app.test_client().post("/login?next=//evil.com", data={"username": "bob", "password": "secret123"})
    assert "evil.com" not in r.location


def test_admin_only(app):
    c = app.test_client()
    login(c, "bob")
    assert c.get("/admin/").status_code == 403
    assert c.post("/admin/invites", data={}).status_code == 403
    a = app.test_client()
    login(a, "alice")
    assert a.get("/admin/").status_code == 200


def test_csrf_enforced():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "t"})
    with app.app_context():
        u = User(username="x", display_name="X", cash=1000)
        u.set_password("secret123")
        db.session.add(u)
        db.session.commit()
    assert app.test_client().post("/login", data={"username": "x", "password": "secret123"}).status_code == 400


def test_login_rate_limit(app):
    c = app.test_client()
    for _ in range(5):
        c.post("/login", data={"username": "bob", "password": "wrong"})
    r = c.post("/login", data={"username": "bob", "password": "secret123"})   # even the right one is refused now
    assert r.status_code == 429
    assert login(app.test_client(), "carol").status_code == 302                # other users unaffected


def test_ratelimit_window_expires():
    ratelimit.reset_all()
    for t in range(3):
        ratelimit.record_failure(("ip", "u"), 100, at=1000 + t)
    assert ratelimit.is_locked(("ip", "u"), 3, 100, at=1010)
    assert not ratelimit.is_locked(("ip", "u"), 3, 100, at=1200)


# ---- first-run setup and invites -----------------------------------------------------------

@pytest.fixture
def empty_app():
    ratelimit.reset_all()
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "t",
                       "WTF_CSRF_ENABLED": False, "START_CASH": 500.0})


def test_first_run_setup_flow(empty_app):
    c = empty_app.test_client()
    r = c.get("/")
    assert r.status_code == 302 and "/setup" in r.location
    assert c.get("/setup").status_code == 200
    r = c.post("/setup", data={"display_name": "Boss", "username": "boss", "password": "longenough1"})
    assert r.status_code == 302
    with empty_app.app_context():
        boss = User.query.filter_by(username="boss").first()
        assert boss.is_admin and boss.cash == 500.0
    assert c.get("/").status_code == 200
    # setup is one-time only
    assert "/setup" not in c.get("/setup").location
    assert c.post("/setup", data={"display_name": "Evil", "username": "evil", "password": "longenough1"}).status_code == 302
    with empty_app.app_context():
        assert User.query.filter_by(username="evil").first() is None


def _invite(app, **kw):
    with app.app_context():
        inv = Invite(token="tok123", created_by=1, **kw)
        db.session.add(inv)
        db.session.commit()


def test_join_with_invite(app):
    _invite(app, max_uses=1)
    c = app.test_client()
    assert c.get("/join/tok123").status_code == 200
    r = c.post("/join/tok123", data={"display_name": "New Pal", "username": "newpal", "password": "longenough1"})
    assert r.status_code == 302
    u = User.query.filter_by(username="newpal").first()
    assert u and not u.is_admin and u.cash == app.config["START_CASH"]
    assert Invite.query.filter_by(token="tok123").first().uses == 1
    assert app.test_client().get("/join/tok123").status_code == 404           # single use is now spent


@pytest.mark.parametrize("kw", [{"revoked": True}, {"expires_at": now() - timedelta(days=1)}])
def test_invalid_invites(app, kw):
    _invite(app, **kw)
    assert app.test_client().get("/join/tok123").status_code == 404
    r = app.test_client().post("/join/tok123", data={"display_name": "X", "username": "xyz", "password": "longenough1"})
    assert r.status_code == 404 and User.query.filter_by(username="xyz").first() is None
    assert app.test_client().get("/join/nope").status_code == 404


@pytest.mark.parametrize("fields,msg", [
    ({"username": "bob", "password": "longenough1"}, b"taken"),
    ({"username": "a", "password": "longenough1"}, b"3-20"),
    ({"username": "okname", "password": "short"}, b"at least 8"),
    ({"username": "Bad Name!", "password": "longenough1"}, b"3-20"),
])
def test_join_validation(app, fields, msg):
    _invite(app)
    r = app.test_client().post("/join/tok123", data={"display_name": "Someone", **fields})
    assert msg in r.data
    assert Invite.query.first().uses == 0


def test_admin_creates_and_revokes_invites(app):
    c = app.test_client()
    login(c, "alice")
    c.post("/admin/invites", data={"days": "7", "max_uses": "3"})
    inv = Invite.query.first()
    assert inv.max_uses == 3 and inv.expires_at and inv.is_valid()
    assert inv.token in c.get("/admin/").data.decode()
    c.post(f"/admin/invites/{inv.id}/revoke")
    assert not Invite.query.first().is_valid()


# ---- market creation, management and the rest of the site over HTTP -------------------------

def test_create_market_over_http(app, users):
    c = app.test_client()
    login(c, "bob")
    r = c.post("/markets/new", data={"title": "Will pizza win?", "kind": "multiple_choice",
                                     "options": "Pizza | 60\nTacos | 40", "description": "vote!",
                                     "about_user": str(users["carol"].id), "b": "100",
                                     "closes_at": "", "tz_offset": "0"})
    assert r.status_code == 302
    m = Market.query.filter_by(title="Will pizza win?").first()
    assert m.creator_id == users["bob"].id and m.restricted_user_id == users["carol"].id
    assert m.price_map()[oid(m, "Pizza")] == pytest.approx(0.6)


def test_create_market_validation_errors(app):
    c = app.test_client()
    login(c, "bob")
    for data, msg in [({"title": "x", "kind": "yes_no"}, b"title"),
                      ({"title": "Valid title", "kind": "multiple_choice", "options": "Only one"}, b"2 to 12"),
                      ({"title": "Valid title", "kind": "multiple_choice", "options": "A\nA"}, b"different"),
                      ({"title": "Valid title", "kind": "bogus"}, b"type"),
                      ({"title": "Valid title", "kind": "yes_no", "yes_prob": "150"}, b"between 1 and 99"),
                      ({"title": "Valid title", "kind": "yes_no", "closes_at": "2001-01-01T10:00"}, b"future")]:
        r = c.post("/markets/new", data=data, follow_redirects=True)
        assert msg in r.data, (data, r.data[:200])
    assert Market.query.count() == 0


def test_close_time_converted_from_browser_local(app):
    c = app.test_client()
    login(c, "bob")
    future = (now() + timedelta(days=3)).replace(second=0, microsecond=0)
    # a browser at UTC-5 reports getTimezoneOffset() == 300; local wall-clock is UTC minus 5h
    local = (future - timedelta(minutes=300)).strftime("%Y-%m-%dT%H:%M")
    c.post("/markets/new", data={"title": "Closes soon", "kind": "yes_no", "closes_at": local, "tz_offset": "300"})
    assert Market.query.first().closes_at == future


def test_only_creator_or_admin_can_manage(app, make_market, users):
    m = make_market(creator="bob")
    target = oid(m, "A")
    carol = app.test_client()
    login(carol, "carol")
    assert carol.get(f"/market/{m.id}/manage").status_code == 403
    assert carol.post(f"/market/{m.id}/resolve", data={"outcome": target}).status_code == 403
    assert carol.post(f"/market/{m.id}/void").status_code == 403
    assert Market.query.get(m.id).status == "open"
    bob = app.test_client()
    login(bob, "bob")
    assert bob.get(f"/market/{m.id}/manage").status_code == 200
    bob.post(f"/market/{m.id}/resolve", data={"outcome": target, "note": "done"})
    assert Market.query.get(m.id).status == "resolved"


def test_admin_override_and_void_over_http(app, make_market):
    m = make_market(creator="bob")
    alice = app.test_client()
    login(alice, "alice")
    alice.post(f"/market/{m.id}/void", data={"note": "stale"})
    assert Market.query.get(m.id).status == "void"


def test_buy_sell_and_pages_over_http(app, make_market):
    m = make_market()
    c = app.test_client()
    login(c, "bob")
    o = m.outcomes[1].id
    assert b"Bought" in c.post(f"/market/{m.id}/buy", data={"outcome": o, "dollars": "50"}, follow_redirects=True).data
    assert c.get(f"/market/{m.id}").status_code == 200
    assert c.get(f"/api/market/{m.id}/history").json["points"]
    assert c.get(f"/api/market/{m.id}/preview?outcome={o}&dollars=10").json["shares"] > 10
    assert c.get("/api/markets").json["markets"][0]["title"] == "Who wins?"
    assert c.get("/profile").status_code == 200 and c.get("/leaderboard").status_code == 200
    assert b"Sold" in c.post(f"/market/{m.id}/sell", data={"outcome": o, "shares": "all"}, follow_redirects=True).data


def test_restricted_user_blocked_over_http(app, make_market, users):
    m = make_market(restricted_user_id=users["bob"].id)
    c = app.test_client()
    login(c, "bob")
    assert b"about you" in c.post(f"/market/{m.id}/buy", data={"outcome": m.outcomes[0].id, "dollars": "5"},
                                  follow_redirects=True).data
    assert b'name="dollars"' not in c.get(f"/market/{m.id}").data


def test_dashboard_search_filter_sort(app, make_market):
    make_market(title="Alpha market")
    b = make_market(title="Beta market")
    c = app.test_client()
    assert b"Alpha market" in c.get("/").data
    page = c.get("/?q=beta").data
    assert b"Beta market" in page and b"Alpha market" not in page
    from app import trading
    trading.void_market(b.id)
    assert b"Beta market" not in c.get("/?filter=open").data
    assert b"Beta market" in c.get("/?filter=done").data
    assert c.get("/?sort=volume").status_code == 200 and c.get("/?sort=closing").status_code == 200


def test_comments(app, make_market):
    m = make_market()
    c = app.test_client()
    assert c.post(f"/market/{m.id}/comment", data={"body": "hi"}).status_code == 302   # to login
    assert Comment.query.count() == 0
    login(c, "bob")
    c.post(f"/market/{m.id}/comment", data={"body": "<b>bold</b> take"})
    c.post(f"/market/{m.id}/comment", data={"body": ""})
    assert Comment.query.count() == 1
    page = c.get(f"/market/{m.id}").data
    assert b"&lt;b&gt;bold&lt;/b&gt; take" in page          # escaped, not rendered as HTML


def test_csv_export_and_password_change(app, make_market):
    m = make_market()
    c = app.test_client()
    login(c, "bob")
    c.post(f"/market/{m.id}/buy", data={"outcome": m.outcomes[0].id, "dollars": "25"})
    r = c.get("/profile/export.csv")
    assert r.mimetype == "text/csv" and b"buy" in r.data and b"25.00" in r.data
    assert b"at least 8" in c.post("/password", data={"old": "secret123", "new": "short"}).data
    assert c.post("/password", data={"old": "secret123", "new": "brandnewpw1"}).status_code == 302
    assert login(app.test_client(), "bob", "brandnewpw1").status_code == 302
