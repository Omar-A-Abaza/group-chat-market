import re
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import ratelimit
from .models import Invite, User, db

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
MIN_PASSWORD = 8


def _safe_next(target):
    if target and not urlparse(target).netloc and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("views.dashboard")


def create_user(username, display_name, password, is_admin=False):
    """Validate and add a user (not committed). Raises ValueError with a friendly message."""
    username = (username or "").strip().lower()
    display_name = (display_name or "").strip()
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3-20 letters, numbers or underscores.")
    if not 1 <= len(display_name) <= 40:
        raise ValueError("Display name must be 1-40 characters.")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
    if User.query.filter_by(username=username).first():
        raise ValueError("That username is taken.")
    user = User(username=username, display_name=display_name, is_admin=is_admin,
                cash=current_app.config["START_CASH"])
    user.set_password(password)
    db.session.add(user)
    return user


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        cfg = current_app.config
        uname = request.form.get("username", "").strip().lower()
        key = (request.remote_addr, uname)
        if ratelimit.is_locked(key, cfg["LOGIN_MAX_FAILURES"], cfg["LOGIN_WINDOW_SECONDS"]):
            flash("Too many failed attempts. Try again in a few minutes.", "error")
            return render_template("login.html"), 429
        user = User.query.filter_by(username=uname).first()
        if user and user.check_password(request.form.get("password", "")):
            ratelimit.clear(key)
            login_user(user, remember=True)
            return redirect(_safe_next(request.args.get("next")))
        ratelimit.record_failure(key, cfg["LOGIN_WINDOW_SECONDS"])
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("views.dashboard"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old, new = request.form.get("old", ""), request.form.get("new", "")
        if not current_user.check_password(old):
            flash("Current password is wrong.", "error")
        elif len(new) < MIN_PASSWORD:
            flash(f"New password must be at least {MIN_PASSWORD} characters.", "error")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Password changed.", "ok")
            return redirect(url_for("views.profile"))
    return render_template("password.html")


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First run only: create the admin account for this group."""
    if User.query.first() is not None:
        return redirect(url_for("views.dashboard"))
    if request.method == "POST":
        try:
            user = create_user(request.form.get("username"), request.form.get("display_name"),
                               request.form.get("password"), is_admin=True)
            db.session.commit()
            login_user(user, remember=True)
            flash("Your group is ready. Invite friends from the Admin page.", "ok")
            return redirect(url_for("views.dashboard"))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
    return render_template("setup.html")


@bp.route("/join/<token>", methods=["GET", "POST"])
def join(token):
    invite = Invite.query.filter_by(token=token).first()
    if invite is None or not invite.is_valid():
        return render_template("join.html", invalid=True), 404
    if request.method == "POST":
        try:
            user = create_user(request.form.get("username"), request.form.get("display_name"),
                               request.form.get("password"))
            invite.uses += 1
            db.session.commit()
            login_user(user, remember=True)
            flash(f"Welcome! You start with ${user.cash:,.0f}.", "ok")
            return redirect(url_for("views.dashboard"))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
    return render_template("join.html", invalid=False)
