import json
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    cash = db.Column(db.Float, default=1000.0, nullable=False)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Market(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question = db.Column(db.String(256), nullable=False)
    b = db.Column(db.Float, default=250.0, nullable=False)
    status = db.Column(db.String(16), default="open", nullable=False)  # open / resolved
    winning_outcome_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=now)
    subject = db.relationship("User")
    outcomes = db.relationship("Outcome", order_by="Outcome.sort_order", cascade="all, delete-orphan", back_populates="market")

    def live_outcomes(self):
        return [o for o in self.outcomes if not o.eliminated]

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
    outcome_id = db.Column(db.Integer, db.ForeignKey("outcome.id"), nullable=False)
    kind = db.Column(db.String(8), nullable=False)  # buy / sell / payout
    shares = db.Column(db.Float, nullable=False)  # always positive; kind gives the direction
    dollars = db.Column(db.Float, nullable=False)
    prices_after = db.Column(db.Text, default="{}")
    created_at = db.Column(db.DateTime, default=now)
    user = db.relationship("User")
    outcome = db.relationship("Outcome")
    market = db.relationship("Market")


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
