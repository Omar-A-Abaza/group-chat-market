import math
import random

import pytest

from app import market_math as mm


def test_prices_sum_to_one():
    q = [random.uniform(-50, 300) for _ in range(10)]
    assert sum(mm.prices(q, 250)) == pytest.approx(1)
    assert mm.prices([0] * 10, 250) == pytest.approx([0.1] * 10)


def test_closed_form_buy_matches_cost_difference():
    q = [0, 10, 30, 5]
    b = 100
    for i in range(4):
        d = mm.shares_for_dollars(q, b, i, 50)
        after = list(q)
        after[i] += d
        assert mm.cost(after, b) - mm.cost(q, b) == pytest.approx(50)


def test_buy_then_sell_round_trips():
    q = [0.0] * 5
    d = mm.shares_for_dollars(q, 250, 2, 80)
    after = list(q)
    after[2] += d
    assert mm.refund_for_shares(after, 250, 2, d) == pytest.approx(80)


def test_buying_raises_price():
    q = [0.0] * 4
    before = mm.prices(q, 100)[1]
    q[1] += mm.shares_for_dollars(q, 100, 1, 100)
    assert mm.prices(q, 100)[1] > before


def test_starting_odds_hold():
    probs = [5, 10, 20, 65]
    q = mm.initial_q_for_probs(probs, 250)
    assert min(q) == pytest.approx(0)
    assert mm.prices(q, 250) == pytest.approx([p / 100 for p in probs])
    with pytest.raises(ValueError):
        mm.initial_q_for_probs([0, 1], 10)


def test_elimination_renormalizes():
    q = [0, 20, 40, 60]
    p = mm.prices(q, 100)
    p2 = mm.prices(mm.eliminate(q, 3), 100)
    assert sum(p2) == pytest.approx(1)
    assert p2[0] / p2[1] == pytest.approx(p[0] / p[1])


def test_numerically_stable_large_q():
    q = [0, 1e5, 2e5]
    assert all(math.isfinite(x) for x in mm.prices(q, 250))
    assert math.isfinite(mm.shares_for_dollars(q, 250, 0, 100))
