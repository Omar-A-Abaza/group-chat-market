import json
import re
from datetime import date, datetime, timedelta, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

KINDS = ("yes_no", "multiple_choice", "date_windows")
KIND_LABELS = {"yes_no": "Yes / No", "multiple_choice": "Multiple choice", "date_windows": "Date windows"}
STATUS_LABELS = {"open": "Open", "closed": "Closed", "resolved": "Resolved", "void": "Cancelled"}


def parse_window_end(label):
    """Last day of a window label: 'Before 2027' -> 2026-12-31, '2027 Q2' -> 2027-06-30. Else None."""
    m = re.fullmatch(r"\s*Before (\d{4})\s*", label)
    if m:
        return date(int(m.group(1)) - 1, 12, 31)
    m = re.fullmatch(r"\s*(\d{4}) Q([1-4])\s*", label)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        first_next = date(y + (q == 4), 1 if q == 4 else q * 3 + 1, 1)
        return first_next - timedelta(days=1)
    return None


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    cash = db.Column(db.Float, default=1000.0, nullable=False)
    created_at = db.Column(db.DateTime, default=now)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def initials(self):
        parts = [p for p in re.split(r"\s+", self.display_name.strip()) if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def hue(self):
        """Stable colour for the avatar."""
        return sum(ord(c) for c in self.username) * 37 % 360


class Invite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=now)
    expires_at = db.Column(db.DateTime)          # None = never
    max_uses = db.Column(db.Integer)             # None = unlimited
    uses = db.Column(db.Integer, default=0, nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False)

    def is_valid(self, at=None):
        at = at or now()
        if self.revoked:
            return False
        if self.expires_at and self.expires_at < at:
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        return True


class Market(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    kind = db.Column(db.String(24), default="multiple_choice", nullable=False)
    b = db.Column(db.Float, default=250.0, nullable=False)
    status = db.Column(db.String(16), default="open", nullable=False)  # open/closed/resolved/void
    closes_at = db.Column(db.DateTime)
    restricted_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # may not bet (e.g. it's about them)
    winning_outcome_id = db.Column(db.Integer)
    resolution_note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=now)
    creator = db.relationship("User", foreign_keys=[creator_id])
    restricted_user = db.relationship("User", foreign_keys=[restricted_user_id])
    outcomes = db.relationship("Outcome", order_by="Outcome.sort_order", cascade="all, delete-orphan",
                               back_populates="market")

    @property
    def is_active(self):
        return self.status in ("open", "closed")

    def live_outcomes(self):
        return [o for o in self.outcomes if not o.eliminated]

    def can_manage(self, user):
        return bool(user and user.is_authenticated and (user.is_admin or user.id == self.creator_id))

    def winner(self):
        return next((o for o in self.outcomes if o.id == self.winning_outcome_id), None)

    def price_map(self):
        """{outcome_id: price}. Eliminated outcomes are 0; a resolved market is 1/0."""
        from . import market_math as mm
        if self.status == "resolved":
            return {o.id: (1.0 if o.id == self.winning_outcome_id else 0.0) for o in self.outcomes}
        live = self.live_outcomes()
        out = {o.id: 0.0 for o in self.outcomes}
        if live:
            for o, p in zip(live, mm.prices([o.q for o in live], self.b)):
                out[o.id] = p
        return out


class Outcome(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("market.id"), nullable=False)
    label = db.Column(db.String(128), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    q = db.Column(db.Float, default=0.0, nullable=False)
    eliminated = db.Column(db.Boolean, default=False, nullable=False)
    ends_on = db.Column(db.Date)  # date_windows: last day of the window; None = open-ended
    market = db.relationship("Market", back_populates="outcomes")


class Position(db.Model):
    __table_args__ = (db.UniqueConstraint("user_id", "outcome_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    outcome_id = db.Column(db.Integer, db.ForeignKey("outcome.id"), nullable=False)
    shares = db.Column(db.Float, default=0.0, nullable=False)
    cost = db.Column(db.Float, default=0.0, nullable=False)  # cost basis of shares still held
    user = db.relationship("User")
    outcome = db.relationship("Outcome")


class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    market_id = db.Column(db.Integer, db.ForeignKey("market.id"), nullable=False)
    outcome_id = db.Column(db.Integer, db.ForeignKey("outcome.id"))
    kind = db.Column(db.String(8), nullable=False)  # buy / sell / payout / refund
    shares = db.Column(db.Float, nullable=False)    # always positive; kind gives the direction
    dollars = db.Column(db.Float, nullable=False)
    prices_after = db.Column(db.Text, default="{}")
    created_at = db.Column(db.DateTime, default=now)
    user = db.relationship("User")
    outcome = db.relationship("Outcome")
    market = db.relationship("Market")


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("market.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=now)
    user = db.relationship("User")


class PriceSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("market.id"), nullable=False)
    prices = db.Column(db.Text, nullable=False)  # JSON {outcome_id: price}
    created_at = db.Column(db.DateTime, default=now)

    def data(self):
        return json.loads(self.prices)


class NetWorthSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    value = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=now)
