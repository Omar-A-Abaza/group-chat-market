import json

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for, flash
from flask_login import current_user, login_required

from . import login_manager, trading
from .models import (Market, NetWorthSnapshot, Outcome, Position, PriceSnapshot, Trade, User)

bp = Blueprint("views", __name__)


def leaderboard_rows():
    cache = {}
    rows = [(u, trading.net_worth(u, cache)) for u in User.query.all()]
    rows.sort(key=lambda r: -r[1])
    return rows


@bp.route("/")
def dashboard():
    cards = []
    for m in Market.query.order_by(Market.id).all():
        pm = m.price_map()
        top = sorted(m.outcomes, key=lambda o: -pm[o.id])[:3]
        cards.append({"market": m, "top": [(o, pm[o.id]) for o in top],
                      "winner": db_get_outcome(m.winning_outcome_id)})
    return render_template("dashboard.html", cards=cards, board=leaderboard_rows()[:5])


def db_get_outcome(oid):
    return Outcome.query.get(oid) if oid else None


@bp.route("/market/<int:mid>")
def market(mid):
    m = Market.query.get_or_404(mid)
    pm = m.price_map()
    mine = {p.outcome_id: p for p in Position.query.filter_by(user_id=current_user.id).all()} \
        if current_user.is_authenticated else {}
    trades = Trade.query.filter_by(market_id=m.id).order_by(Trade.id.desc()).limit(25).all()
    holders = {}
    for p in Position.query.join(Outcome).filter(Outcome.market_id == m.id, Position.shares > 0).all():
        holders.setdefault(p.outcome_id, []).append(p)
    return render_template("market.html", m=m, pm=pm, mine=mine, trades=trades, holders=holders,
                           can_bet=(current_user.is_authenticated and m.status == "open"
                            and m.subject_id != current_user.id))


@bp.route("/market/<int:mid>/buy", methods=["POST"])
@login_required
def buy(mid):
    try:
        shares = trading.buy(current_user, int(request.form["outcome"]), request.form["dollars"])
        flash(f"Bought {shares:.2f} shares.", "ok")
    except (trading.TradeError, ValueError, KeyError) as e:
        flash(str(e) or "Invalid input.", "error")
    return redirect(url_for("views.market", mid=mid))


@bp.route("/market/<int:mid>/sell", methods=["POST"])
@login_required
def sell(mid):
    try:
        oid = int(request.form["outcome"])
        raw = request.form.get("shares", "").strip().lower()
        if raw in ("all", ""):
            pos = Position.query.filter_by(user_id=current_user.id, outcome_id=oid).first()
            raw = pos.shares if pos else 0
        refund = trading.sell(current_user, oid, raw)
        flash(f"Sold for {refund:.2f}.", "ok")
    except (trading.TradeError, ValueError, KeyError) as e:
        flash(str(e) or "Invalid input.", "error")
    return redirect(url_for("views.market", mid=mid))


@bp.route("/api/market/<int:mid>/preview")
@login_required
def preview(mid):
    try:
        oid = int(request.args["outcome"])
        if "dollars" in request.args:
            d = float(request.args["dollars"])
            shares, _ = trading.preview(current_user, oid, dollars=d)
            return jsonify(shares=shares, payout=shares, dollars=d)
        s = float(request.args["shares"])
        _, refund = trading.preview(current_user, oid, shares=s)
        return jsonify(shares=s, refund=refund)
    except (trading.TradeError, ValueError, KeyError) as e:
        return jsonify(error=str(e) or "Invalid input."), 400


@bp.route("/api/market/<int:mid>/history")
def history(mid):
    m = Market.query.get_or_404(mid)
    snaps = PriceSnapshot.query.filter_by(market_id=m.id).order_by(PriceSnapshot.id).all()
    return jsonify(outcomes=[{"id": o.id, "label": o.label} for o in m.outcomes],
                   points=[{"t": s.created_at.isoformat(), "p": s.data()} for s in snaps])


@bp.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html", board=leaderboard_rows())


@bp.route("/api/leaderboard")
def leaderboard_api():
    board = leaderboard_rows()
    series = {}
    for s in NetWorthSnapshot.query.order_by(NetWorthSnapshot.id).all():
        series.setdefault(s.user_id, []).append({"t": s.created_at.isoformat(), "v": s.value})
    return jsonify(board=[{"id": u.id, "name": u.display_name, "value": v} for u, v in board],
                   series=series)


@bp.route("/profile")
@bp.route("/profile/<int:uid>")
def profile(uid=None):
    if uid is None and not current_user.is_authenticated:
        return login_manager.unauthorized()
    user = User.query.get_or_404(uid) if uid else current_user
    cache = {}
    rows = []
    for p in Position.query.filter_by(user_id=user.id).all():
        if p.shares <= 0:
            continue
        o = p.outcome
        price = 0.0 if (o.eliminated or o.market.status != "open") else \
            cache.setdefault(o.market_id, o.market.price_map())[o.id]
        rows.append({"pos": p, "outcome": o, "price": price, "value": p.shares * price,
                     "pnl": p.shares * price - p.cost})
    trades = Trade.query.filter_by(user_id=user.id).order_by(Trade.id.desc()).limit(50).all()
    return render_template("profile.html", u=user, rows=rows, trades=trades,
                           worth=trading.net_worth(user))
