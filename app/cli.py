import json
import random
import secrets
import tomllib
from datetime import timedelta
from pathlib import Path

import click
from flask import current_app

from . import markets, trading
from .auth import create_user
from .models import Invite, Market, User, db, now


def register(app):
    @app.cli.command("create-admin")
    @click.argument("username")
    @click.option("--name", default=None, help="Display name (defaults to the username).")
    @click.password_option()
    def create_admin(username, name, password):
        """Create an admin account without using the setup page."""
        try:
            create_user(username, name or username, password, is_admin=True)
            db.session.commit()
        except ValueError as e:
            raise click.ClickException(str(e))
        click.echo(f"Admin '{username}' created.")

    @app.cli.command("seed")
    @click.argument("accounts", type=click.Path(exists=True))
    @click.option("--out", default="passwords.local.txt", help="Where to write generated passwords.")
    def seed(accounts, out):
        """Bulk-create users from a TOML file ([[users]] with username, display_name, is_admin)."""
        data = tomllib.loads(Path(accounts).read_text())
        lines = []
        for entry in data["users"]:
            if User.query.filter_by(username=entry["username"].lower()).first():
                continue
            pw = secrets.token_urlsafe(9)
            try:
                create_user(entry["username"], entry["display_name"], pw, bool(entry.get("is_admin")))
            except ValueError as e:
                raise click.ClickException(f"{entry['username']}: {e}")
            lines.append(f"{entry['username'].lower()}\t{pw}")
        db.session.commit()
        if lines:
            with open(out, "a") as f:
                f.write("\n".join(lines) + "\n")
            click.echo(f"Created {len(lines)} users; passwords appended to {out}")
        else:
            click.echo("No new users.")

    @app.cli.command("reset-password")
    @click.argument("username")
    def reset_password(username):
        user = User.query.filter_by(username=username.lower()).first()
        if not user:
            raise click.ClickException("No such user")
        pw = secrets.token_urlsafe(9)
        user.set_password(pw)
        db.session.commit()
        click.echo(f"{user.username}: {pw}")

    @app.cli.command("check-markets")
    def check_markets():
        """Close markets past their close time and expire date windows (also runs in the server)."""
        closed = trading.close_expired_markets()
        elim = trading.auto_eliminate_expired()
        click.echo(f"{len(closed)} market(s) closed, {len(elim)} option(s) eliminated.")

    @app.cli.command("demo-data")
    def demo_data():
        """Fill an EMPTY database with fake users, markets and trades (for screenshots and demos)."""
        if User.query.first():
            raise click.ClickException("Database is not empty; refusing to add demo data.")
        rnd = random.Random(42)
        names = [("ava", "Ava Chen", True), ("liam", "Liam Ortiz", False), ("mia", "Mia Patel", False),
                 ("noah", "Noah Kim", False), ("zoe", "Zoe Adams", False), ("eli", "Eli Brooks", False)]
        users = []
        for uname, dn, adm in names:
            users.append(create_user(uname, dn, "demo-password", is_admin=adm))
        db.session.commit()
        year = now().year + 1
        specs = [
            (users[0], "Will the group trip happen this summer?", "yes_no", "Everyone has to confirm by June.", None),
            (users[1], "Who wins the fantasy league?", "multiple_choice", "Final standings at the end of the season.",
             "Ava\nLiam\nMia\nNoah\nZoe"),
            (users[2], "When will Liam finally finish his thesis?", "date_windows", "", None),
            (users[3], "Does Zoe's new startup get its first customer by March?", "yes_no", "", None),
            (users[4], "What movie do we watch Friday?", "multiple_choice", "", "Dune\nBarbie\nOppenheimer\nSomething new"),
        ]
        made = []
        for creator, title, kind, desc, opts in specs:
            pairs = markets.parse_options(kind, opts, start_year=year, years=2)
            restricted = users[1].id if "Liam" in title else None   # the market is about Liam
            made.append(markets.create_market(creator, title, kind, pairs, description=desc, b=150.0,
                                              closes_at=now() + timedelta(days=rnd.randint(10, 90)),
                                              restricted_user_id=restricted))
        for _ in range(70):
            u = rnd.choice(users)
            m = rnd.choice(made)
            live = m.live_outcomes()
            weights = [1 + (3 if i in (0, 2) else 0) for i in range(len(live))]
            o = rnd.choices(live, weights)[0]
            try:
                trading.buy(u, o.id, rnd.choice([10, 20, 25, 40, 50]))
            except trading.TradeError:
                pass
        db.session.commit()
        _spread_timestamps(rnd, made)
        click.echo("Demo data created. Users log in with password 'demo-password' (e.g. ava, an admin).")


def _spread_timestamps(rnd, made, days=12):
    """Backdate rows so demo graphs span days instead of one instant."""
    from .models import NetWorthSnapshot, PriceSnapshot, Trade
    end, start = now(), now() - timedelta(days=days)

    def spread(rows):
        n = len(rows)
        stamps = sorted(start + (end - start) * rnd.random() for _ in range(n))
        for row, t in zip(rows, stamps):
            row.created_at = t

    for m in made:
        m.created_at = start
        spread(PriceSnapshot.query.filter_by(market_id=m.id).order_by(PriceSnapshot.id).all()[1:])
        PriceSnapshot.query.filter_by(market_id=m.id).order_by(PriceSnapshot.id).first().created_at = start
        spread(Trade.query.filter_by(market_id=m.id).order_by(Trade.id).all())
    spread(NetWorthSnapshot.query.order_by(NetWorthSnapshot.id).all())
    db.session.commit()
