import json
import os
import secrets
import stat
import tomllib
from pathlib import Path

import click
from flask import current_app

from .models import Market, Outcome, PriceSnapshot, User, db


def _words_password():
    return secrets.token_urlsafe(9)


def register(app):
    @app.cli.command("seed")
    @click.option("--accounts", type=click.Path(), default=None)
    def seed(accounts):
        """Create users + one 'When will X get married?' market each. Idempotent."""
        from . import DEFAULT_WINDOWS
        root = Path(current_app.root_path).parent
        path = Path(accounts) if accounts else root / "accounts.local.toml"
        if not path.exists():
            path = root / "accounts.example.toml"
        click.echo(f"Using {path.name}")
        data = tomllib.loads(path.read_text())
        lines = []
        for entry in data["users"]:
            uname = entry["username"].lower()
            user = User.query.filter_by(username=uname).first()
            if user is None:
                pw = _words_password()
                user = User(username=uname, display_name=entry["display_name"],
                            is_admin=bool(entry.get("is_admin", False)),
                            cash=current_app.config["START_CASH"])
                user.set_password(pw)
                db.session.add(user)
                db.session.flush()
                lines.append(f"{uname}\t{pw}")
            if not Market.query.filter_by(subject_id=user.id).first():
                m = Market(subject_id=user.id, b=current_app.config["DEFAULT_B"],
                           question=f"When will {user.display_name} get married?")
                db.session.add(m)
                db.session.flush()
                for i, label in enumerate(DEFAULT_WINDOWS):
                    db.session.add(Outcome(market_id=m.id, label=label, sort_order=i, q=0.0))
                db.session.flush()
                db.session.add(PriceSnapshot(market_id=m.id, prices=json.dumps(m.price_map())))
        db.session.commit()
        if lines:
            out = root / "passwords.local.txt"
            with open(out, "a") as f:
                f.write("\n".join(lines) + "\n")
            os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
            click.echo(f"Created {len(lines)} users; passwords appended to {out.name}")
        else:
            click.echo("No new users.")

    @app.cli.command("reset-password")
    @click.argument("username")
    def reset_password(username):
        user = User.query.filter_by(username=username.lower()).first()
        if not user:
            raise click.ClickException("No such user")
        pw = _words_password()
        user.set_password(pw)
        db.session.commit()
        click.echo(f"{user.username}: {pw}")
