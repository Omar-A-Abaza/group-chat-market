from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .models import User, db

bp = Blueprint("auth", __name__)


def _safe_next(target):
    if target and not urlparse(target).netloc and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("views.dashboard")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username", "").strip().lower()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=True)
            return redirect(_safe_next(request.args.get("next")))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old, new = request.form.get("old", ""), request.form.get("new", "")
        if not current_user.check_password(old):
            flash("Current password is wrong.", "error")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "error")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Password changed.", "ok")
            return redirect(url_for("views.dashboard"))
    return render_template("password.html")
