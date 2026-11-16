"""Trading operations. All run under a global lock and commit their own transaction."""
import json
import threading
from datetime import date

from . import market_math as mm
from .models import (Market, NetWorthSnapshot, Outcome, Position, PriceSnapshot, Trade, User,
                     db, now)

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
        if o.eliminated or not o.market.is_active:
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


def _tradable_outcome(user, outcome_id):
    outcome = db.session.get(Outcome, outcome_id)
    if outcome is None:
        raise TradeError("Unknown option.")
    market = outcome.market
    if market.status == "closed":
        raise TradeError("Betting on this market has closed.")
    if market.status != "open":
        raise TradeError("This market is finished.")
    if outcome.eliminated:
        raise TradeError("This option has been eliminated.")
    if market.restricted_user_id == user.id:
        raise TradeError("You can't bet on a market that's about you.")
    return market, outcome


def _qs(market, outcome):
    live = market.live_outcomes()
    return [o.q for o in live], live.index(outcome)


def preview(user, outcome_id, dollars=None, shares=None):
    """Return (shares, dollars) for a hypothetical buy (dollars) or sell (shares)."""
    market, outcome = _tradable_outcome(user, outcome_id)
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
            market, outcome = _tradable_outcome(user, outcome_id)
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
            market, outcome = _tradable_outcome(user, outcome_id)
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
    """An option can no longer happen: its shares become worthless, the rest rescale to 100%."""
    with LOCK:
        try:
            outcome = db.session.get(Outcome, outcome_id)
            if outcome is None:
                raise TradeError("Unknown option.")
            market = outcome.market
            if not market.is_active:
                raise TradeError("Market is finished.")
            if outcome.eliminated:
                raise TradeError("Already eliminated.")
            if len(market.live_outcomes()) <= 2:
                raise TradeError("A market needs at least two live options; resolve it instead.")
            outcome.eliminated = True
            db.session.flush()
            _snapshot(market)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def resolve(market_id, outcome_id, note=""):
    """The winning option pays $1/share and the market freezes."""
    with LOCK:
        try:
            market = db.session.get(Market, market_id)
            outcome = db.session.get(Outcome, outcome_id)
            if market is None or outcome is None or outcome.market_id != market.id:
                raise TradeError("Unknown market/option.")
            if not market.is_active:
                raise TradeError("Market already finished.")
            if outcome.eliminated:
                raise TradeError("That option was eliminated.")
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
            market.resolution_note = (note or "").strip()[:500]
            db.session.flush()
            _snapshot(market)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def void_market(market_id, note=""):
    """Cancel a market: everyone gets back what they spent (buys minus sells)."""
    with LOCK:
        try:
            market = db.session.get(Market, market_id)
            if market is None:
                raise TradeError("Unknown market.")
            if not market.is_active:
                raise TradeError("Market already finished.")
            net = {}
            for t in Trade.query.filter_by(market_id=market.id).all():
                if t.kind == "buy":
                    net[t.user_id] = net.get(t.user_id, 0.0) + t.dollars
                elif t.kind == "sell":
                    net[t.user_id] = net.get(t.user_id, 0.0) - t.dollars
            for uid, amount in net.items():
                if amount > 0.004:
                    db.session.get(User, uid).cash += amount
                    db.session.add(Trade(user_id=uid, market_id=market.id, outcome_id=None,
                                         kind="refund", shares=0.0, dollars=amount, prices_after="{}"))
            ids = [o.id for o in market.outcomes]
            for pos in Position.query.filter(Position.outcome_id.in_(ids)).all():
                pos.shares = 0.0
                pos.cost = 0.0
            market.status = "void"
            market.resolution_note = (note or "").strip()[:500]
            db.session.flush()
            _snapshot(market)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def close_expired_markets(at=None):
    """Stop trading on open markets whose close time has passed. Returns the closed markets' titles."""
    at = at or now()
    done = []
    with LOCK:
        try:
            for m in Market.query.filter(Market.status == "open", Market.closes_at.isnot(None),
                                         Market.closes_at <= at).all():
                m.status = "closed"
                done.append(m.title)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return done


def auto_eliminate_expired(today=None):
    """Eliminate date-window options whose end date is before `today`, in all active markets.

    Holders of an expired option lose those shares; everyone else's prices rescale to 100%.
    The last two live options of a market are never both eliminated away: at least one stays live.
    Returns a list of (market title, option label).
    """
    today = today or date.today()
    done = []
    with LOCK:
        try:
            for market in Market.query.filter(Market.status.in_(("open", "closed")),
                                              Market.kind == "date_windows").all():
                changed = False
                for o in sorted(market.live_outcomes(), key=lambda o: o.ends_on or date.max):
                    if o.ends_on and o.ends_on < today and len(market.live_outcomes()) > 1:
                        o.eliminated = True
                        db.session.flush()
                        done.append((market.title, o.label))
                        changed = True
                if changed:
                    _snapshot(market)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return done


def volume(market_id):
    """Total dollars bought in a market."""
    total = db.session.query(db.func.coalesce(db.func.sum(Trade.dollars), 0.0)).filter(
        Trade.market_id == market_id, Trade.kind == "buy").scalar()
    return float(total or 0.0)
