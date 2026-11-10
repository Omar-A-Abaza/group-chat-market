from datetime import date

import pytest

from app import trading
from app.models import Outcome, parse_window_end
from tests.conftest import market_of


def oid(m, label):
    return next(o.id for o in m.outcomes if o.label == label)


def test_parse_window_end():
    assert parse_window_end("Before 2027") == date(2026, 12, 31)
    assert parse_window_end("2027 Q1") == date(2027, 3, 31)
    assert parse_window_end("2027 Q2") == date(2027, 6, 30)
    assert parse_window_end("2027 Q4") == date(2027, 12, 31)
    assert parse_window_end("2029 or later / never") is None


def test_nothing_expires_early(app):
    assert trading.auto_eliminate_expired(date(2026, 12, 31)) == []


def test_expired_window_eliminated_and_rest_rescale(app, users):
    m = market_of("alice")
    before, q1 = oid(m, "Before 2027"), oid(m, "2027 Q1")
    trading.buy(users["bob"], before, 100)
    trading.buy(users["carol"], q1, 100)
    done = trading.auto_eliminate_expired(date(2027, 1, 1))
    assert ("When will Alice get married?", "Before 2027") in done
    pm = m.price_map()
    assert pm[before] == 0
    assert sum(pm.values()) == pytest.approx(1)
    # loser's shares worthless, other holder untouched
    assert trading.net_worth(users["bob"]) == pytest.approx(900)
    assert trading.net_worth(users["carol"]) > 900
    with pytest.raises(trading.TradeError):
        trading.buy(users["bob"], before, 1)


def test_idempotent_and_multi_quarter_catch_up(app):
    first = trading.auto_eliminate_expired(date(2027, 7, 1))
    assert len(first) == 3 * 3  # Before 2027, Q1, Q2 in each of 3 markets
    assert trading.auto_eliminate_expired(date(2027, 7, 1)) == []
    m = market_of("alice")
    assert sum(m.price_map().values()) == pytest.approx(1)


def test_open_ended_and_last_window_never_eliminated(app):
    trading.auto_eliminate_expired(date(2100, 1, 1))
    m = market_of("alice")
    live = m.live_outcomes()
    assert [o.label for o in live] == ["2029 or later / never"]
    assert m.price_map()[live[0].id] == pytest.approx(1)


def test_resolved_markets_untouched(app, users):
    m = market_of("alice")
    trading.resolve(m.id, oid(m, "2027 Q2"))
    trading.auto_eliminate_expired(date(2100, 1, 1))
    assert not any(o.eliminated for o in m.outcomes)
