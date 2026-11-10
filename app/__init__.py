import os

from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from config import Config

from .models import User, db

login_manager = LoginManager()
login_manager.login_view = "auth.login"
csrf = CSRFProtect()

DEFAULT_WINDOWS = ["Before 2027", "2027 Q1", "2027 Q2", "2027 Q3", "2027 Q4",
                   "2028 Q1", "2028 Q2", "2028 Q3", "2028 Q4", "2029 or later / never"]


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=False)
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

    @app.template_filter("money")
    def money(x):
        return f"${x:,.2f}"

    @app.template_filter("pct")
    def pct(x):
        return f"{x * 100:.1f}%"

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", msg="Not allowed."), 403

    @app.errorhandler(404)
    def notfound(e):
        return render_template("error.html", msg="Not found."), 404

    with app.app_context():
        db.create_all()
    return app
