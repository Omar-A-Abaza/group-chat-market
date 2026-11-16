import pytest

from app import trading
from app.models import NetWorthSnapshot, Position, PriceSnapshot, db
from tests.conftest import oid


def test_buy_moves_price_and_cash(make_market, users):
    m = make_market()
    a = oid(m, "A")
    before = m.price_map()[a]
    n = PriceSnapshot.query.filter_by(market_id=m.id).count()
    shares = trading.buy(users["bob"], a, 100)
    assert shares > 100
    assert users["bob"].cash == pytest.approx(900)
    assert m.price_map()[a] > before
    assert sum(m.price_map().values()) == pytest.approx(1)
    assert PriceSnapshot.query.filter_by(market_id=m.id).count() == n + 1
    assert NetWorthSnapshot.query.count() >= 3


def test_anyone_can_bet_on_their_own_market_unless_restricted(make_market, users):
    m = make_market(creator="alice")
    trading.buy(users["alice"], oid(m, "A"), 10)  # creators may bet by default


def test_restricted_user_cannot_bet(make_market, users):
    m = make_market(restricted_user_id=users["bob"].id)
    with pytest.raises(trading.TradeError, match="about you"):
        trading.buy(users["bob"], oid(m, "A"), 10)
    trading.buy(users["carol"], oid(m, "A"), 10)


def test_no_overspend_or_nonpositive(make_market, users):
    o = oid(make_market(), "A")
    for amt in (1000.01, 0, -5):
        with pytest.raises(trading.TradeError):
            trading.buy(users["bob"], o, amt)
    assert users["bob"].cash == 1000


def test_no_overselling(make_market, users):
    o = oid(make_market(), "A")
    shares = trading.buy(users["bob"], o, 50)
    with pytest.raises(trading.TradeError):
        trading.sell(users["bob"], o, shares + 1)
    with pytest.raises(trading.TradeError):
        trading.sell(users["carol"], o, 1)


def test_buy_sell_round_trip(make_market, users):
    o = oid(make_market(), "A")
    shares = trading.buy(users["bob"], o, 75)
    assert trading.sell(users["bob"], o, shares) == pytest.approx(75, abs=0.01)
    assert users["bob"].cash == pytest.approx(1000, abs=0.01)
    assert Position.query.filter_by(user_id=users["bob"].id).first().shares == 0


def test_eliminate_rejects_trades_and_renormalizes(make_market, users):
    m = make_market()
    a, b = oid(m, "A"), oid(m, "B")
    trading.buy(users["bob"], a, 50)
    trading.eliminate_outcome(a)
    with pytest.raises(trading.TradeError):
        trading.buy(users["carol"], a, 10)
    pm = m.price_map()
    assert pm[a] == 0 and sum(pm.values()) == pytest.approx(1)
    assert pm[b] == pytest.approx(1 / 3)
    assert trading.net_worth(users["bob"]) == pytest.approx(950)


def test_cannot_eliminate_down_to_one_option(make_market):
    m = make_market(labels=["A", "B"])
    with pytest.raises(trading.TradeError):
        trading.eliminate_outcome(oid(m, "A"))


def test_resolve_pays_winners_and_freezes(make_market, users):
    m = make_market()
    win, lose = oid(m, "B"), oid(m, "C")
    s = trading.buy(users["bob"], win, 100)
    trading.buy(users["carol"], lose, 100)
    trading.resolve(m.id, win, "It was B")
    assert users["bob"].cash == pytest.approx(900 + s)
    assert users["carol"].cash == pytest.approx(900)
    assert m.status == "resolved" and m.resolution_note == "It was B"
    assert m.winner().label == "B"
    with pytest.raises(trading.TradeError):
        trading.buy(users["bob"], win, 1)
    with pytest.raises(trading.TradeError):
        trading.resolve(m.id, win)
    assert trading.net_worth(users["carol"]) == pytest.approx(900)


def test_cannot_resolve_to_eliminated(make_market, users):
    m = make_market()
    o = oid(m, "A")
    trading.eliminate_outcome(o)
    with pytest.raises(trading.TradeError):
        trading.resolve(m.id, o)


def test_void_refunds_net_spend(make_market, users):
    m = make_market()
    a, b = oid(m, "A"), oid(m, "B")
    trading.buy(users["bob"], a, 100)
    trading.buy(users["bob"], b, 50)
    s = Position.query.filter_by(user_id=users["bob"].id, outcome_id=a).first().shares
    refund = trading.sell(users["bob"], a, s / 2)       # partial sell realises some money
    trading.buy(users["carol"], b, 80)
    trading.void_market(m.id, "changed our minds")
    assert m.status == "void"
    assert users["bob"].cash == pytest.approx(1000)     # exactly back to start
    assert users["carol"].cash == pytest.approx(1000)
    assert trading.net_worth(users["bob"]) == pytest.approx(1000)
    with pytest.raises(trading.TradeError):
        trading.buy(users["bob"], a, 1)
    assert refund > 0


def test_closed_market_rejects_trades_but_can_resolve(make_market, users):
    from datetime import timedelta
    from app.models import now
    m = make_market()
    o = oid(m, "A")
    trading.buy(users["bob"], o, 20)
    m.closes_at = now() - timedelta(minutes=1)
    db.session.commit()
    assert trading.close_expired_markets() == ["Who wins?"]
    assert m.status == "closed"
    with pytest.raises(trading.TradeError, match="closed"):
        trading.buy(users["carol"], o, 5)
    with pytest.raises(trading.TradeError):
        trading.sell(users["bob"], o, 1)
    trading.resolve(m.id, o)
    assert m.status == "resolved"


def test_yes_no_market(make_market, users):
    m = make_market(kind="yes_no", title="Will it rain?")
    yes, no = oid(m, "Yes"), oid(m, "No")
    trading.buy(users["bob"], yes, 100)
    assert m.price_map()[yes] > 0.5 > m.price_map()[no]
    trading.resolve(m.id, no)
    assert users["bob"].cash == pytest.approx(900)


def test_volume(make_market, users):
    m = make_market()
    trading.buy(users["bob"], oid(m, "A"), 30)
    trading.buy(users["carol"], oid(m, "B"), 20)
    assert trading.volume(m.id) == pytest.approx(50)
