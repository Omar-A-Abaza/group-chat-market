from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import market_math as mm
from . import trading
from .models import Market, Outcome, PriceSnapshot, Trade, User, db

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*a, **kw):
        if not current_user.is_admin:
            abort(403)
        return f(*a, **kw)
    return wrapper


@bp.route("/")
@admin_required
def index():
    return render_template("admin_index.html", markets=Market.query.order_by(Market.id).all(),
                           users=User.query.order_by(User.id).all())


@bp.route("/market/<int:mid>")
@admin_required
def market(mid):
    m = Market.query.get_or_404(mid)
    has_trades = Trade.query.filter_by(market_id=m.id).count() > 0
    return render_template("admin_market.html", m=m, pm=m.price_map(), has_trades=has_trades)


@bp.route("/market/<int:mid>/configure", methods=["POST"])
@admin_required
def configure(mid):
    """Replace windows / starting odds / b. Only allowed before any trade."""
    m = Market.query.get_or_404(mid)
    if Trade.query.filter_by(market_id=m.id).count() or m.status != "open":
        flash("Can't reconfigure after trading has started.", "error")
        return redirect(url_for("admin.market", mid=mid))
    try:
        b = float(request.form["b"])
        if b <= 0:
            raise ValueError("b must be positive")
        labels, probs = [], []
        for line in request.form["windows"].splitlines():
            if not line.strip():
                continue
            label, _, p = line.partition("|")
            labels.append(label.strip())
            probs.append(float(p) if p.strip() else None)
        if len(labels) < 2:
            raise ValueError("Need at least 2 windows")
        if all(p is None for p in probs):
            qs = [0.0] * len(labels)
        elif any(p is None for p in probs):
            raise ValueError("Give a % for every window or for none")
        else:
            qs = mm.initial_q_for_probs(probs, b)
    except (ValueError, KeyError) as e:
        flash(f"Invalid: {e}", "error")
        return redirect(url_for("admin.market", mid=mid))
    with trading.LOCK:
        for o in list(m.outcomes):
            db.session.delete(o)
        db.session.flush()
        m.b = b
        for i, (l, q) in enumerate(zip(labels, qs)):
            db.session.add(Outcome(market_id=m.id, label=l, sort_order=i, q=q))
        db.session.flush()
        db.session.add(PriceSnapshot(market_id=m.id, prices=__import__("json").dumps(m.price_map())))
        db.session.commit()
    flash("Market reconfigured.", "ok")
    return redirect(url_for("admin.market", mid=mid))


@bp.route("/outcome/<int:oid>/eliminate", methods=["POST"])
@admin_required
def eliminate(oid):
    o = Outcome.query.get_or_404(oid)
    try:
        trading.eliminate_outcome(oid)
        flash("Window eliminated.", "ok")
    except trading.TradeError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.market", mid=o.market_id))


@bp.route("/market/<int:mid>/resolve", methods=["POST"])
@admin_required
def resolve(mid):
    try:
        trading.resolve(mid, int(request.form["outcome"]))
        flash("Market resolved and paid out.", "ok")
    except (trading.TradeError, ValueError, KeyError) as e:
        flash(str(e) or "Invalid input.", "error")
    return redirect(url_for("admin.market", mid=mid))


@bp.route("/user/<int:uid>/password", methods=["POST"])
@admin_required
def reset_password(uid):
    u = User.query.get_or_404(uid)
    new = request.form.get("password", "")
    if len(new) < 6:
        flash("Password must be at least 6 characters.", "error")
    else:
        u.set_password(new)
        db.session.commit()
        flash(f"Password reset for {u.username}.", "ok")
    return redirect(url_for("admin.index"))
