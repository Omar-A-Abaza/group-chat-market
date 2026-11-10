"""Trading operations. All run under a global lock and commit their own transaction."""
import json
import threading

from . import market_math as mm
from .models import (Market, NetWorthSnapshot, Outcome, Position, PriceSnapshot, Trade, User,
                     db)

LOCK = threading.RLock()
EPS = 1e-9


class TradeError(Exception):
    pass


def cents(x):
    return round(x + 0.0, 2)


def net_worth(user, cache=None):
    cache = {} if cache is None else cache
    total = user.cash
    for pos in Position.query.filter_by(user_id=user.id).all():
        if pos.shares <= 0:
            continue
        o = pos.outcome
        if o.eliminated or o.market.status != "open":
            continue
        if o.market_id not in cache:
            cache[o.market_id] = o.market.price_map()
        total += pos.shares * cache[o.market_id][o.id]
    return total


def _snapshot(market):
    db.session.add(PriceSnapshot(market_id=market.id, prices=json.dumps(market.price_map())))
    cache = {}
    for u in User.query.all():
        db.session.add(NetWorthSnapshot(user_id=u.id, value=net_worth(u, cache)))


def _open_outcome(user, outcome_id):
    outcome = db.session.get(Outcome, outcome_id)
    if outcome is None:
        raise TradeError("Unknown outcome.")
    market = outcome.market
    if market.status != "open":
        raise TradeError("This market is resolved.")
    if outcome.eliminated:
        raise TradeError("This window has been eliminated.")
    if market.subject_id == user.id:
        raise TradeError("You can't bet on your own market.")
    return market, outcome


def _qs(market, outcome):
    live = market.live_outcomes()
    return [o.q for o in live], live.index(outcome)


def preview(user, outcome_id, dollars=None, shares=None):
    """Return (shares, dollars) for a hypothetical buy (dollars) or sell (shares)."""
    market, outcome = _open_outcome(user, outcome_id)
    qs, i = _qs(market, outcome)
    if dollars is not None:
        return mm.shares_for_dollars(qs, market.b, i, dollars), dollars
    return shares, mm.refund_for_shares(qs, market.b, i, shares)


def buy(user, outcome_id, dollars):
    with LOCK:
        try:
            db.session.refresh(user)
            dollars = cents(float(dollars))
            if not dollars > 0:
                raise TradeError("Amount must be positive.")
            market, outcome = _open_outcome(user, outcome_id)
            if dollars > user.cash + EPS:
                raise TradeError("Not enough cash.")
            qs, i = _qs(market, outcome)
            shares = mm.shares_for_dollars(qs, market.b, i, dollars)
            outcome.q += shares
            user.cash -= dollars
            pos = Position.query.filter_by(user_id=user.id, outcome_id=outcome.id).first()
            if pos is None:
                pos = Position(user_id=user.id, outcome_id=outcome.id, shares=0.0, cost=0.0)
                db.session.add(pos)
            pos.shares += shares
            pos.cost += dollars
            db.session.flush()
            db.session.add(Trade(user_id=user.id, market_id=market.id, outcome_id=outcome.id,
                                 kind="buy", shares=shares, dollars=dollars,
                                 prices_after=json.dumps(market.price_map())))
            _snapshot(market)
            db.session.commit()
            return shares
        except Exception:
            db.session.rollback()
            raise


def sell(user, outcome_id, shares):
    with LOCK:
        try:
            db.session.refresh(user)
            shares = float(shares)
            if not shares > 0:
                raise TradeError("Amount must be positive.")
            market, outcome = _open_outcome(user, outcome_id)
            pos = Position.query.filter_by(user_id=user.id, outcome_id=outcome.id).first()
            held = pos.shares if pos else 0.0
            if shares > held + 1e-6:
                raise TradeError("You don't own that many shares.")
            shares = min(shares, held)
            qs, i = _qs(market, outcome)
            refund = mm.refund_for_shares(qs, market.b, i, shares)
            frac = shares / held
            pos.cost -= pos.cost * frac
            pos.shares = held - shares if held - shares > 1e-9 else 0.0
            if pos.shares == 0.0:
                pos.cost = 0.0
            outcome.q -= shares
            user.cash += refund
            db.session.flush()
            db.session.add(Trade(user_id=user.id, market_id=market.id, outcome_id=outcome.id,
                                 kind="sell", shares=shares, dollars=refund,
                                 prices_after=json.dumps(market.price_map())))
            _snapshot(market)
            db.session.commit()
            return refund
        except Exception:
            db.session.rollback()
            raise


def eliminate_outcome(outcome_id):
    """A window passed unmarried: its shares become worthless, the rest rescale to 100%."""
    with LOCK:
        try:
            outcome = db.session.get(Outcome, outcome_id)
            if outcome is None:
                raise TradeError("Unknown outcome.")
            market = outcome.market
            if market.status != "open":
                raise TradeError("Market is resolved.")
            if outcome.eliminated:
                raise TradeError("Already eliminated.")
            if len(market.live_outcomes()) <= 1:
                raise TradeError("Can't eliminate the last live window.")
            outcome.eliminated = True
            db.session.flush()
            _snapshot(market)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def resolve(market_id, outcome_id):
    """Wedding happened in this window: winners get $1/share, market freezes."""
    with LOCK:
        try:
            market = db.session.get(Market, market_id)
            outcome = db.session.get(Outcome, outcome_id)
            if market is None or outcome is None or outcome.market_id != market.id:
                raise TradeError("Unknown market/outcome.")
            if market.status != "open":
                raise TradeError("Market already resolved.")
            if outcome.eliminated:
                raise TradeError("That window was eliminated.")
            ids = [o.id for o in market.outcomes]
            for pos in Position.query.filter(Position.outcome_id.in_(ids)).all():
                if pos.shares > 0 and pos.outcome_id == outcome.id:
                    pos.user.cash += pos.shares
                    db.session.add(Trade(user_id=pos.user_id, market_id=market.id,
                                         outcome_id=outcome.id, kind="payout",
                                         shares=pos.shares, dollars=pos.shares, prices_after="{}"))
                pos.shares = 0.0
                pos.cost = 0.0
            market.status = "resolved"
            market.winning_outcome_id = outcome.id
            db.session.flush()
            _snapshot(market)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
