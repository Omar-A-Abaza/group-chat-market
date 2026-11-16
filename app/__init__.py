import os
import time

from flask import Flask, redirect, render_template, request, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from config import Config

from .models import User, db

login_manager = LoginManager()
login_manager.login_view = "auth.login"
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///") and ":memory:" not in uri:
        os.makedirs(os.path.dirname(uri[len("sqlite:///"):]), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(uid):
        return db.session.get(User, int(uid))

    from . import admin, auth, cli, views
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    app.register_blueprint(admin.bp)
    cli.register(app)

    @app.before_request
    def first_run_redirect():
        """With no users yet, everything leads to the one-time setup page."""
        if request.endpoint in (None, "static", "auth.setup"):
            return None
        if User.query.first() is None:
            return redirect(url_for("auth.setup"))

    @app.context_processor
    def inject_globals():
        return {"group_name": app.config["GROUP_NAME"]}

    from .models import KIND_LABELS, STATUS_LABELS
    app.jinja_env.globals.update(KIND_LABELS=KIND_LABELS, STATUS_LABELS=STATUS_LABELS)

    @app.template_filter("money")
    def money(x):
        return f"${x:,.2f}"

    @app.template_filter("pct")
    def pct(x):
        return f"{x * 100:.0f}%" if x >= 0.995 or x <= 0.005 else f"{x * 100:.1f}%"

    @app.template_filter("cents")
    def cents(x):
        return f"{x * 100:.0f}¢"

    @app.template_filter("utc")
    def utc(dt):
        """ISO string the browser turns into local time (see static/app.js)."""
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", msg="You're not allowed to do that."), 403

    @app.errorhandler(404)
    def notfound(e):
        return render_template("error.html", msg="Page not found."), 404

    with app.app_context():
        db.create_all()
    return app


def start_scheduler(app, interval_seconds=300):
    """Background thread: close markets past their close time and expire date windows."""
    import threading

    def loop():
        while True:
            try:
                with app.app_context():
                    from . import trading
                    for title in trading.close_expired_markets():
                        app.logger.info("Closed market: %s", title)
                    for title, label in trading.auto_eliminate_expired():
                        app.logger.info("Auto-eliminated %s in %s", label, title)
            except Exception:
                app.logger.exception("scheduled check failed")
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="market-checker", daemon=True).start()
