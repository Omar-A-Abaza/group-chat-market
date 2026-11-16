"""Creating and configuring markets: option templates per kind and validation."""
import json
from datetime import date, datetime

from . import market_math as mm
from .models import KINDS, Market, Outcome, PriceSnapshot, db, parse_window_end

MAX_OPTIONS = 12
MIN_B, MAX_B = 10.0, 5000.0


class MarketError(ValueError):
    pass


def date_window_labels(start_year, years=3):
    """'Before Y', then every quarter for `years` years, then 'Y+N or later / never'."""
    labels = [f"Before {start_year}"]
    for y in range(start_year, start_year + years):
        labels += [f"{y} Q{q}" for q in range(1, 5)]
    labels.append(f"{start_year + years} or later / never")
    return labels


def parse_options(kind, raw_options, start_year=None, years=3, yes_prob=None):
    """Return [(label, prob_or_None)] for a market kind. Lines may be 'Label | percent'."""
    if kind not in KINDS:
        raise MarketError("Unknown market type.")
    if kind == "yes_no":
        if yes_prob in (None, ""):
            return [("Yes", None), ("No", None)]
        try:
            p = float(yes_prob)
        except ValueError:
            raise MarketError("Starting chance must be a number.")
        if not 1 <= p <= 99:
            raise MarketError("Starting chance must be between 1 and 99.")
        return [("Yes", p), ("No", 100 - p)]
    if kind == "date_windows":
        year = int(start_year or date.today().year + 1)
        if not 2000 <= year <= 2200 or not 1 <= int(years) <= 10:
            raise MarketError("Pick a sensible start year and 1-10 years.")
        return [(l, None) for l in date_window_labels(year, int(years))]
    pairs = []
    for line in (raw_options or "").splitlines():
        if not line.strip():
            continue
        label, _, p = line.partition("|")
        label = label.strip()
        if not label:
            continue
        try:
            prob = float(p) if p.strip() else None
        except ValueError:
            raise MarketError(f"'{p.strip()}' isn't a number.")
        pairs.append((label, prob))
    return pairs


def _initial_qs(pairs, b):
    probs = [p for _, p in pairs]
    if all(p is None for p in probs):
        return [0.0] * len(pairs)
    if any(p is None for p in probs):
        raise MarketError("Give a starting % for every option, or for none.")
    try:
        return mm.initial_q_for_probs(probs, b)
    except ValueError:
        raise MarketError("Starting percentages must all be above 0.")


def validate_options(pairs):
    labels = [l for l, _ in pairs]
    if not 2 <= len(labels) <= MAX_OPTIONS:
        raise MarketError(f"A market needs 2 to {MAX_OPTIONS} options.")
    if any(len(l) > 100 for l in labels):
        raise MarketError("Option labels are limited to 100 characters.")
    if len({l.lower() for l in labels}) != len(labels):
        raise MarketError("Options must be different from each other.")


def create_market(creator, title, kind, pairs, *, description="", b=250.0, closes_at=None,
                  restricted_user_id=None, now=None):
    title = (title or "").strip()
    if not 3 <= len(title) <= 200:
        raise MarketError("Give the market a title (3-200 characters).")
    if len((description or "")) > 2000:
        raise MarketError("Description is too long.")
    if not MIN_B <= b <= MAX_B:
        raise MarketError(f"Liquidity must be between {MIN_B:g} and {MAX_B:g}.")
    validate_options(pairs)
    if closes_at and closes_at <= (now or datetime.utcnow()):
        raise MarketError("The close time must be in the future.")
    qs = _initial_qs(pairs, b)
    m = Market(creator_id=creator.id, title=title, description=(description or "").strip(), kind=kind,
               b=b, closes_at=closes_at, restricted_user_id=restricted_user_id or None)
    db.session.add(m)
    db.session.flush()
    for i, ((label, _), q) in enumerate(zip(pairs, qs)):
        ends = parse_window_end(label) if kind == "date_windows" else None
        db.session.add(Outcome(market_id=m.id, label=label, sort_order=i, q=q, ends_on=ends))
    db.session.flush()
    db.session.add(PriceSnapshot(market_id=m.id, prices=json.dumps(m.price_map())))
    db.session.commit()
    return m


def reconfigure_market(market, pairs, b):
    """Replace options / starting odds / liquidity. Caller ensures there are no trades yet."""
    if not MIN_B <= b <= MAX_B:
        raise MarketError(f"Liquidity must be between {MIN_B:g} and {MAX_B:g}.")
    validate_options(pairs)
    qs = _initial_qs(pairs, b)
    for o in list(market.outcomes):
        db.session.delete(o)
    db.session.flush()
    market.b = b
    for i, ((label, _), q) in enumerate(zip(pairs, qs)):
        ends = parse_window_end(label) if market.kind == "date_windows" else None
        db.session.add(Outcome(market_id=market.id, label=label, sort_order=i, q=q, ends_on=ends))
    db.session.flush()
    db.session.refresh(market)
    db.session.add(PriceSnapshot(market_id=market.id, prices=json.dumps(market.price_map())))
    db.session.commit()
