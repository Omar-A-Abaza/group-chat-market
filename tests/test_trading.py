import pytest

from app import trading
from app.models import Position, PriceSnapshot, NetWorthSnapshot, db
from tests.conftest import market_of


def oid(market, label):
    return next(o.id for o in market.outcomes if o.label == label)


def test_buy_moves_price_and_cash(app, users):
    m = market_of("alice")
    o = oid(m, "2027 Q1")
    before = m.price_map()[o]
    n_snaps = PriceSnapshot.query.filter_by(market_id=m.id).count()
    shares = trading.buy(users["bob"], o, 100)
    assert shares > 100
    assert users["bob"].cash == pytest.approx(900)
    assert m.price_map()[o] > before
    assert sum(m.price_map().values()) == pytest.approx(1)
    assert PriceSnapshot.query.filter_by(market_id=m.id).count() == n_snaps + 1
    assert NetWorthSnapshot.query.count() >= 3


def test_self_bet_blocked(app, users):
    m = market_of("alice")
    with pytest.raises(trading.TradeError):
        trading.buy(users["alice"], oid(m, "2027 Q1"), 10)


def test_no_overspend_or_nonpositive(app, users):
    o = oid(market_of("alice"), "2027 Q1")
    for amt in (1000.01, 0, -5):
        with pytest.raises(trading.TradeError):
            trading.buy(users["bob"], o, amt)
    assert users["bob"].cash == 1000


def test_no_overselling(app, users):
    o = oid(market_of("alice"), "2027 Q1")
    shares = trading.buy(users["bob"], o, 50)
    with pytest.raises(trading.TradeError):
        trading.sell(users["bob"], o, shares + 1)
    with pytest.raises(trading.TradeError):
        trading.sell(users["carol"], o, 1)


def test_buy_sell_round_trip_money(app, users):
    o = oid(market_of("alice"), "2027 Q1")
    shares = trading.buy(users["bob"], o, 75)
    refund = trading.sell(users["bob"], o, shares)
    assert refund == pytest.approx(75, abs=0.01)
    assert users["bob"].cash == pytest.approx(1000, abs=0.01)
    assert Position.query.filter_by(user_id=users["bob"].id).first().shares == 0


def test_eliminate_rejects_trades_and_renormalizes(app, users):
    m = market_of("alice")
    o1, o2 = oid(m, "Before 2027"), oid(m, "2027 Q1")
    trading.buy(users["bob"], o1, 50)
    trading.eliminate_outcome(o1)
    with pytest.raises(trading.TradeError):
        trading.buy(users["carol"], o1, 10)
    pm = m.price_map()
    assert pm[o1] == 0
    assert sum(pm.values()) == pytest.approx(1)
    assert pm[o2] == pytest.approx(1 / 9)
    # eliminated shares are worth nothing in net worth
    assert trading.net_worth(users["bob"]) == pytest.approx(950)


def test_resolve_pays_out_and_freezes(app, users):
    m = market_of("alice")
    win, lose = oid(m, "2027 Q2"), oid(m, "2028 Q1")
    s = trading.buy(users["bob"], win, 100)
    trading.buy(users["carol"], lose, 100)
    trading.resolve(m.id, win)
    assert users["bob"].cash == pytest.approx(900 + s)
    assert users["carol"].cash == pytest.approx(900)
    assert m.status == "resolved"
    for o in (win, lose):
        with pytest.raises(trading.TradeError):
            trading.buy(users["bob"], o, 1)
    with pytest.raises(trading.TradeError):
        trading.resolve(m.id, win)
    assert trading.net_worth(users["carol"]) == pytest.approx(900)


def test_cannot_resolve_to_eliminated(app, users):
    m = market_of("alice")
    o = oid(m, "Before 2027")
    trading.eliminate_outcome(o)
    with pytest.raises(trading.TradeError):
        trading.resolve(m.id, o)


def test_net_worth_includes_positions(app, users):
    o = oid(market_of("alice"), "2027 Q1")
    trading.buy(users["bob"], o, 100)
    nw = trading.net_worth(users["bob"])
    assert 900 < nw < 1100
