import csv
import io
from datetime import timedelta

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from . import login_manager, markets, trading
from .models import (KIND_LABELS, KINDS, Comment, Market, NetWorthSnapshot, Outcome, Position,
                     PriceSnapshot, Trade, User, db, now)

bp = Blueprint("views", __name__)


def leaderboard_rows():
    cache = {}
    rows = [(u, trading.net_worth(u, cache)) for u in User.query.all()]
    rows.sort(key=lambda r: -r[1])
    return rows


def _volumes():
    q = db.session.query(Trade.market_id, db.func.sum(Trade.dollars), db.func.count(Trade.id)).filter(
        Trade.kind == "buy").group_by(Trade.market_id)
    return {mid: (float(v or 0), n) for mid, v, n in q}


def _card(m, vols):
    pm = m.price_map()
    outs = sorted(m.outcomes, key=lambda o: -pm[o.id])
    return {"market": m, "pm": pm, "top": [(o, pm[o.id]) for o in outs[:3]],
            "yes": next((pm[o.id] for o in m.outcomes if o.label == "Yes"), None) if m.kind == "yes_no" else None,
            "volume": vols.get(m.id, (0.0, 0))[0], "trades": vols.get(m.id, (0.0, 0))[1]}


@bp.route("/")
def dashboard():
    q = (request.args.get("q") or "").strip()
    flt = request.args.get("filter", "open")
    sort = request.args.get("sort", "new")
    query = Market.query
    if q:
        query = query.filter(Market.title.ilike(f"%{q}%"))
    if flt == "open":
        query = query.filter(Market.status == "open")
    elif flt == "soon":
        query = query.filter(Market.status == "open", Market.closes_at.isnot(None),
                             Market.closes_at <= now() + timedelta(days=7))
    elif flt == "done":
        query = query.filter(Market.status.in_(("resolved", "void", "closed")))
    ms = query.all()
    vols = _volumes()
    if sort == "volume":
        ms.sort(key=lambda m: -vols.get(m.id, (0, 0))[0])
    elif sort == "closing":
        ms.sort(key=lambda m: (m.closes_at is None, m.closes_at or now()))
    else:
        ms.sort(key=lambda m: -m.id)
    feed = Trade.query.filter(Trade.kind == "buy").order_by(Trade.id.desc()).limit(6).all()
    return render_template("dashboard.html", cards=[_card(m, vols) for m in ms], board=leaderboard_rows()[:5],
                           q=q, flt=flt, sort=sort, feed=feed)


@bp.route("/market/<int:mid>")
def market(mid):
    m = db.get_or_404(Market, mid)
    pm = m.price_map()
    mine = {}
    if current_user.is_authenticated:
        mine = {p.outcome_id: p for p in Position.query.filter_by(user_id=current_user.id).all()}
    trades = Trade.query.filter_by(market_id=m.id).order_by(Trade.id.desc()).limit(20).all()
    holders = {}
    for p in Position.query.join(Outcome).filter(Outcome.market_id == m.id, Position.shares > 0).all():
        holders.setdefault(p.outcome_id, []).append(p)
    comments = Comment.query.filter_by(market_id=m.id).order_by(Comment.id.desc()).limit(40).all()
    restricted = current_user.is_authenticated and m.restricted_user_id == current_user.id
    return render_template("market.html", m=m, pm=pm, mine=mine, trades=trades, holders=holders,
                           comments=comments, volume=trading.volume(m.id), restricted=restricted,
                           can_bet=(current_user.is_authenticated and m.status == "open" and not restricted),
                           kind_label=KIND_LABELS[m.kind])


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


@bp.route("/market/<int:mid>/comment", methods=["POST"])
@login_required
def comment(mid):
    m = db.get_or_404(Market, mid)
    body = (request.form.get("body") or "").strip()
    if not 1 <= len(body) <= 500:
        flash("Comments must be 1-500 characters.", "error")
    else:
        db.session.add(Comment(market_id=m.id, user_id=current_user.id, body=body))
        db.session.commit()
    return redirect(url_for("views.market", mid=mid) + "#comments")


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
    m = db.get_or_404(Market, mid)
    snaps = PriceSnapshot.query.filter_by(market_id=m.id).order_by(PriceSnapshot.id).all()
    return jsonify(outcomes=[{"id": o.id, "label": o.label} for o in m.outcomes],
                   points=[{"t": s.created_at.isoformat() + "Z", "p": s.data()} for s in snaps])


@bp.route("/api/markets")
def markets_api():
    vols = _volumes()
    out = []
    for m in Market.query.order_by(Market.id.desc()).all():
        pm = m.price_map()
        out.append({"id": m.id, "title": m.title, "kind": m.kind, "status": m.status,
                    "closes_at": m.closes_at.isoformat() + "Z" if m.closes_at else None,
                    "volume": vols.get(m.id, (0.0, 0))[0],
                    "options": [{"id": o.id, "label": o.label, "price": pm[o.id]} for o in m.outcomes]})
    return jsonify(markets=out)


# ---- creating and managing markets ---------------------------------------------------------

def _local_to_utc(value, tz_offset):
    """'2027-03-01T18:00' typed in the browser + its JS getTimezoneOffset() -> naive UTC datetime."""
    from datetime import datetime
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M")
        return dt + timedelta(minutes=int(tz_offset or 0))
    except ValueError:
        raise markets.MarketError("That close time isn't valid.")


@bp.route("/markets/new", methods=["GET", "POST"])
@login_required
def new_market():
    if request.method == "POST":
        f = request.form
        try:
            kind = f.get("kind", "")
            if kind not in KINDS:
                raise markets.MarketError("Pick a market type.")
            pairs = markets.parse_options(kind, f.get("options"), f.get("start_year") or None,
                                          int(f.get("years") or 3), f.get("yes_prob"))
            try:
                b = float(f.get("b") or current_user_b())
            except ValueError:
                raise markets.MarketError("Liquidity must be a number.")
            about = f.get("about_user") or None
            if about and not db.session.get(User, int(about)):
                raise markets.MarketError("Unknown person.")
            m = markets.create_market(current_user, f.get("title"), kind, pairs,
                                      description=f.get("description"), b=b,
                                      closes_at=_local_to_utc(f.get("closes_at"), f.get("tz_offset")),
                                      restricted_user_id=int(about) if about else None)
            flash("Market created.", "ok")
            return redirect(url_for("views.market", mid=m.id))
        except (markets.MarketError, ValueError) as e:
            db.session.rollback()
            flash(str(e), "error")
    from datetime import date
    return render_template("new_market.html", users=User.query.order_by(User.display_name).all(),
                           kinds=KIND_LABELS, form=request.form, year=date.today().year + 1)


def current_user_b():
    from flask import current_app
    return current_app.config["DEFAULT_B"]


def _manageable(mid):
    m = db.get_or_404(Market, mid)
    if not m.can_manage(current_user):
        abort(403)
    return m


@bp.route("/market/<int:mid>/manage")
@login_required
def manage(mid):
    m = _manageable(mid)
    has_trades = Trade.query.filter_by(market_id=m.id).count() > 0
    return render_template("manage.html", m=m, pm=m.price_map(), has_trades=has_trades)


@bp.route("/market/<int:mid>/resolve", methods=["POST"])
@login_required
def resolve(mid):
    m = _manageable(mid)
    try:
        trading.resolve(m.id, int(request.form["outcome"]), request.form.get("note", ""))
        flash("Market resolved and paid out.", "ok")
    except (trading.TradeError, ValueError, KeyError) as e:
        flash(str(e) or "Invalid input.", "error")
    return redirect(url_for("views.market", mid=mid))


@bp.route("/market/<int:mid>/void", methods=["POST"])
@login_required
def void(mid):
    m = _manageable(mid)
    try:
        trading.void_market(m.id, request.form.get("note", ""))
        flash("Market cancelled and everyone was refunded.", "ok")
    except trading.TradeError as e:
        flash(str(e), "error")
    return redirect(url_for("views.market", mid=mid))


@bp.route("/market/<int:mid>/eliminate/<int:oid>", methods=["POST"])
@login_required
def eliminate(mid, oid):
    m = _manageable(mid)
    o = db.get_or_404(Outcome, oid)
    if o.market_id != m.id:
        abort(404)
    try:
        trading.eliminate_outcome(oid)
        flash("Option eliminated.", "ok")
    except trading.TradeError as e:
        flash(str(e), "error")
    return redirect(url_for("views.manage", mid=mid))


@bp.route("/market/<int:mid>/configure", methods=["POST"])
@login_required
def configure(mid):
    m = _manageable(mid)
    if Trade.query.filter_by(market_id=m.id).count() or m.status != "open" or m.kind == "yes_no":
        flash("Options can only be edited before anyone has traded (and not on Yes/No markets).", "error")
        return redirect(url_for("views.manage", mid=mid))
    try:
        pairs = markets.parse_options(m.kind, request.form.get("options"), None, 3)
        with trading.LOCK:
            markets.reconfigure_market(m, pairs, float(request.form["b"]))
        flash("Market updated.", "ok")
    except (markets.MarketError, ValueError, KeyError) as e:
        db.session.rollback()
        flash(str(e) or "Invalid input.", "error")
    return redirect(url_for("views.manage", mid=mid))


# ---- leaderboard / profile ------------------------------------------------------------------

@bp.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html", board=leaderboard_rows())


@bp.route("/api/leaderboard")
def leaderboard_api():
    board = leaderboard_rows()
    series = {}
    for s in NetWorthSnapshot.query.order_by(NetWorthSnapshot.id).all():
        series.setdefault(s.user_id, []).append({"t": s.created_at.isoformat() + "Z", "v": s.value})
    return jsonify(board=[{"id": u.id, "name": u.display_name, "value": v} for u, v in board],
                   series=series)


@bp.route("/profile")
@bp.route("/profile/<int:uid>")
def profile(uid=None):
    if uid is None and not current_user.is_authenticated:
        return login_manager.unauthorized()
    user = db.get_or_404(User, uid) if uid else current_user
    cache = {}
    rows = []
    for p in Position.query.filter_by(user_id=user.id).all():
        if p.shares <= 0 or not p.outcome.market.is_active:
            continue
        o = p.outcome
        price = 0.0 if o.eliminated else cache.setdefault(o.market_id, o.market.price_map())[o.id]
        rows.append({"pos": p, "outcome": o, "price": price, "value": p.shares * price,
                     "pnl": p.shares * price - p.cost})
    trades = Trade.query.filter_by(user_id=user.id).order_by(Trade.id.desc()).limit(40).all()
    created = Market.query.filter_by(creator_id=user.id).order_by(Market.id.desc()).all()
    return render_template("profile.html", u=user, rows=rows, trades=trades, created=created,
                           worth=trading.net_worth(user))


@bp.route("/profile/export.csv")
@login_required
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time_utc", "market", "option", "type", "shares", "dollars"])
    for t in Trade.query.filter_by(user_id=current_user.id).order_by(Trade.id):
        w.writerow([t.created_at.isoformat(), t.market.title, t.outcome.label if t.outcome else "",
                    t.kind, f"{t.shares:.4f}", f"{t.dollars:.2f}"])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=my-trades.csv"})
