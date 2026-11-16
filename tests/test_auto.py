from datetime import date

import pytest

from app import trading
from app.models import parse_window_end
from tests.conftest import oid


def test_parse_window_end():
    assert parse_window_end("Before 2027") == date(2026, 12, 31)
    assert parse_window_end("2027 Q1") == date(2027, 3, 31)
    assert parse_window_end("2027 Q2") == date(2027, 6, 30)
    assert parse_window_end("2027 Q4") == date(2027, 12, 31)
    assert parse_window_end("2029 or later / never") is None


def test_nothing_expires_early(make_market):
    make_market(kind="date_windows")
    assert trading.auto_eliminate_expired(date(2026, 12, 31)) == []


def test_expired_window_eliminated_and_rest_rescale(make_market, users):
    m = make_market(kind="date_windows", title="When?")
    before, q1 = oid(m, "Before 2027"), oid(m, "2027 Q1")
    trading.buy(users["bob"], before, 100)
    trading.buy(users["carol"], q1, 100)
    done = trading.auto_eliminate_expired(date(2027, 1, 1))
    assert ("When?", "Before 2027") in done
    pm = m.price_map()
    assert pm[before] == 0 and sum(pm.values()) == pytest.approx(1)
    assert trading.net_worth(users["bob"]) == pytest.approx(900)
    assert trading.net_worth(users["carol"]) > 900
    with pytest.raises(trading.TradeError):
        trading.buy(users["bob"], before, 1)


def test_idempotent_and_catches_up(make_market):
    m = make_market(kind="date_windows")
    assert len(trading.auto_eliminate_expired(date(2027, 7, 1))) == 3   # Before 2027, Q1, Q2
    assert trading.auto_eliminate_expired(date(2027, 7, 1)) == []
    assert sum(m.price_map().values()) == pytest.approx(1)


def test_last_window_never_eliminated(make_market):
    m = make_market(kind="date_windows")
    trading.auto_eliminate_expired(date(2100, 1, 1))
    live = m.live_outcomes()
    assert [o.label for o in live] == ["2029 or later / never"]


def test_other_kinds_untouched(make_market):
    m = make_market(labels=["2027 Q1", "2027 Q2", "later"])   # labels look like windows, but kind differs
    assert trading.auto_eliminate_expired(date(2100, 1, 1)) == []
    assert not any(o.eliminated for o in m.outcomes)


def test_resolved_markets_untouched(make_market):
    m = make_market(kind="date_windows")
    trading.resolve(m.id, oid(m, "2027 Q2"))
    trading.auto_eliminate_expired(date(2100, 1, 1))
    assert not any(o.eliminated for o in m.outcomes)
