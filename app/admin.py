import secrets
from datetime import timedelta
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .auth import MIN_PASSWORD
from .models import Invite, Market, User, db, now

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
    invites = Invite.query.order_by(Invite.id.desc()).all()
    return render_template("admin.html", invites=invites, users=User.query.order_by(User.id).all(),
                           markets=Market.query.order_by(Market.id.desc()).all(),
                           now=now(), links={i.id: url_for("auth.join", token=i.token, _external=True)
                                             for i in invites})


@bp.route("/invites", methods=["POST"])
@admin_required
def create_invite():
    try:
        days = int(request.form.get("days") or 0)
        uses = int(request.form.get("max_uses") or 0)
    except ValueError:
        flash("Days and uses must be numbers.", "error")
        return redirect(url_for("admin.index"))
    if days < 0 or uses < 0:
        flash("Days and uses can't be negative.", "error")
        return redirect(url_for("admin.index"))
    inv = Invite(token=secrets.token_urlsafe(12), created_by=current_user.id,
                 expires_at=(now() + timedelta(days=days)) if days else None,
                 max_uses=uses or None)
    db.session.add(inv)
    db.session.commit()
    flash("Invite link created.", "ok")
    return redirect(url_for("admin.index"))


@bp.route("/invites/<int:iid>/revoke", methods=["POST"])
@admin_required
def revoke_invite(iid):
    inv = db.get_or_404(Invite, iid)
    inv.revoked = True
    db.session.commit()
    flash("Invite revoked.", "ok")
    return redirect(url_for("admin.index"))


@bp.route("/user/<int:uid>/password", methods=["POST"])
@admin_required
def reset_password(uid):
    u = db.get_or_404(User, uid)
    new = request.form.get("password", "")
    if len(new) < MIN_PASSWORD:
        flash(f"Password must be at least {MIN_PASSWORD} characters.", "error")
    else:
        u.set_password(new)
        db.session.commit()
        flash(f"Password reset for {u.username}.", "ok")
    return redirect(url_for("admin.index"))
