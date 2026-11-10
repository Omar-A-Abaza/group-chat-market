# Group Chat Market: a fake-money prediction market for the group chat

## Context
Omar wants a small Polymarket/Kalshi-style website for his ~10-person group chat, hosted on this
Raspberry Pi. Everyone starts with $1,000 of fake money. Each friend has a market: "When will <name>
get married?" Others buy shares in the date window they believe in. A dashboard with graphs shows how
the odds move, who bet what, and who is winning. This build is the **skeleton**: working structure
first, then the betting details get refined together. Later versions may add user-created markets,
other bet types (e.g. "type of wife"), self-betting and self-signup.

**Decisions made:** Polymarket-style shares with live prices · date-window outcomes · Cloudflare
quick tunnel (no account needed) · **public** repo, with names and passwords kept only in local
git-ignored files · no betting on your own market (for now) · pre-made accounts with passwords Omar
hands out.

**Standing conventions** (saved to memory in Phase 0): every new project gets a GitHub repo, lives
in `~/Documents/<project>`, gets its own conda env, and is written in Python.

## Environment (checked)
- Pi 5, aarch64, 8 GB RAM, 20 GB free, system Python 3.13. `~/Documents` is empty.
- Not installed: conda, cloudflared, tmux. `sudo` needs a password, so the unattended run cannot use it.
- `gh` is logged in as Omar-A-Abaza and the git identity is set.

## Market type: "When will <name> get married?" with date windows
Each friend's market has date-window outcomes, editable per market by an admin. The defaults are:
`Before 2027 · 2027 Q1 · Q2 · Q3 · Q4 · 2028 Q1 · Q2 · Q3 · Q4 · 2029 or later / never` (10 outcomes).
All the percentages add up to 100% and shift live as money comes in. A YES/NO market is just the
2-outcome case of the same engine, so later binary markets come for free.

## How the betting works (LMSR market maker, N outcomes)
- Each market has a share count `q_i` per outcome and a liquidity `b` (default 250).
- Cost function `C = b·ln(Σ e^(q_i/b))`. Price of outcome i = `e^(q_i/b) / Σ e^(q_j/b)`. The prices are the group's odds and sum to 1.
- **Buy $X of outcome i:** `Δ = b·ln(e^((C+X)/b) − Σ_{j≠i} e^(q_j/b)) − q_i` (closed form).
- **Sell s shares:** refund = `C(before) − C(after removing s)`.
- **Payout:** each share of the winning window pays $1; all others pay $0.
- **Starting odds:** an admin can set opening probabilities p_i through `q_i = b·ln(p_i)` (shift so min is 0).
- **A window passes unmarried:** an admin eliminates it. Its shares become worthless and it drops out of the sum, so the rest rescale to 100%.
- **Wedding happens:** an admin resolves the market to that window, which pays out and freezes it.
- **House subsidy:** at most `b·ln N` per market. This is fake money, so it doesn't matter.
- **Net worth** = cash + Σ shares × current price. This drives the leaderboard.
- Money and share amounts are floats, rounded to cents for display. The tests check the invariants. Use log-sum-exp for numerical stability.

## Stack
Flask + Flask-Login + Flask-SQLAlchemy (SQLite) + Flask-WTF (CSRF), with Jinja templates. The graphs use Chart.js from a
pinned CDN URL in the browser, and the site is served by gunicorn (1 worker, a few threads). A global lock around trades keeps the money math
consistent. Passwords are hashed with werkzeug. Tests use pytest.

## Project layout: `~/Documents/group-chat-market/`
- `environment.yml`: conda env `group-chat-market` (python 3.12, flask, flask-login, flask-sqlalchemy,
  flask-wtf, gunicorn, pytest, python-dotenv).
- `docs/PLAN.md`: a copy of this plan, so later sessions can read it.
- `app/__init__.py`: app factory. `config.py`: reads `.env` (SECRET_KEY, DB path, secure-cookie flag).
- `app/market_math.py`: pure LMSR functions for N outcomes (prices, cost, shares_for_dollars,
  refund_for_shares, initial_q_for_probs, eliminate). No database code.
- `app/models.py`: `User` (username, display_name, password_hash, is_admin, cash), `Market` (subject
  user, question, b, status open/resolved, winning_outcome), `Outcome` (market, label, sort order, q,
  eliminated), `Position` (user, outcome, shares), `Trade` (user, outcome, shares ±, dollars,
  prices-after JSON, time), `PriceSnapshot` (market, prices JSON, time) and `NetWorthSnapshot` (user, value, time).
- `app/trading.py`: `buy()`, `sell()`, `eliminate_outcome()` and `resolve()`. They run under the lock,
  enforce no self-betting, enough cash, enough shares, an open market, a live outcome and positive amounts, and
  write snapshots afterwards.
- `app/auth.py`: login, logout, and change password.
- `app/views.py`:
  - **Dashboard:** a card per friend showing the top 3 windows with %, plus the top of the leaderboard.
  - **Market page:** a row per window with a % bar and buy/sell, a live preview ("$50 → 120.4 shares, pays $120.40 if 2028 Q1"), a line chart with one line per window, a recent-trades feed and a holders list.
  - **Leaderboard:** a net-worth bar chart and net worth over time.
  - **Profile:** cash, positions with value and profit/loss, and trade history.
- `app/admin.py`: admin-only page to edit windows, starting odds and `b`, eliminate windows, resolve
  markets, and reset passwords.
- `app/cli.py`: `flask seed` reads `accounts.local.toml` (falling back to `accounts.example.toml`) and creates
  users, markets with the default windows, and random passwords. The passwords go to `passwords.local.txt` (chmod 600).
  `flask reset-password <user>`.
- `app/templates/*.html` and `app/static/{style.css,charts.js}`: mobile-first dark theme (the group is on phones).
- `accounts.example.toml` (committed, fake names) and `accounts.local.toml` (git-ignored, real friends).
- `.gitignore`: `.env`, `*.local.*`, `instance/`, `*.db`, `__pycache__/`, `.pytest_cache/`.
- `.env.example`, `README.md` (setup, betting math in plain English, admin how-to, start/stop), and `wsgi.py`.
- `deploy/group-chat-market.service` and `deploy/cloudflared.service`: **systemd user units** (no sudo
  needed), running gunicorn on 127.0.0.1:8000 and a quick tunnel to it. `deploy/start.sh` and `stop.sh` wrap
  `systemctl --user start/stop` and print the current tunnel link.
- `tests/`:
  - `test_market_math.py`: prices sum to 1, buy-then-sell round-trips the money, the closed-form buy matches the cost difference, starting odds hold, elimination renormalizes.
  - `test_trading.py`: self-bet blocked, no overspending or overselling, payouts correct, eliminated or resolved outcomes reject trades.
  - `test_auth.py`: login required, admin-only routes, CSRF.

## Phase 0: interactive setup with Omar present (this session, about 10 minutes)
Everything that needs approval or a password happens here, so the long run never waits on anyone.
1. **Omar runs this in his own SSH terminal** (it needs his sudo password):
   `sudo apt install -y tmux && sudo loginctl enable-linger bromargiza`
   (Linger keeps the website's user services running after he logs out and starts them on boot.)
2. **Downloads I run, which Omar approves once each:**
   - Miniforge installer → `~/miniforge3` (no sudo).
   - Create `~/Documents/group-chat-market/` with `environment.yml`, then `conda env create`.
   - cloudflared arm64 binary → `~/.local/bin/cloudflared` (no sudo).
3. `git init`, then copy this plan to `docs/PLAN.md`.
4. Save the project-conventions memory.

## Phase 1+: unattended build in tmux (new session, no approvals needed)
Build notes: implement `docs/PLAN.md` Phase 1+. **Do not** download, install, use sudo or delete
anything. If something is missing, write it in `docs/TODO.md` and carry on.
1. Build the app and tests as laid out above.
2. Run `pytest` until it passes. Run `flask seed` with the example accounts and smoke-test the site.
3. Check `git ls-files` for secrets or real names. Then `gh repo create Omar-A-Abaza/group-chat-market --public --source . --push`.
4. Install and enable the systemd user units. Start them and put the tunnel link in `docs/STATUS.md`.
5. Write `docs/STATUS.md` covering what was built, what was tested, the tunnel link, and next steps.

## Afterwards (with Omar)
Fill in `accounts.local.toml` with the real 10 names, run `flask seed`, send out the passwords, then
refine the betting details.

## Verification
- `pytest` passes, including the LMSR invariants and trading rules.
- Smoke test via Flask's test client and `curl` with a cookie jar: log in, buy, sell, and confirm prices
  moved, cash changed and snapshots were written. Eliminate a window and resolve a test market, then check the payouts.
- On the LAN, `http://192.168.1.96:8000` renders on Omar's phone with the charts working.
- The tunnel link works on mobile data (off Wi-Fi).
- `git ls-files` shows no `.env`, `*.local.*` or `*.db` files.

## Later ideas (not in v1)
User-created markets, YES/NO markets, other bet types ("type of wife"), self-betting toggle,
self-signup or phone-number invites, a fixed domain via a Cloudflare account, comments or trash talk.

## Phase 0 results (done 2026-11-10) — notes for the build
- Miniforge: `~/miniforge3` (conda 26.9.4). `conda init` was NOT run (shell rc files untouched), so
  call tools by full path: env python is `~/miniforge3/envs/group-chat-market/bin/python`, and
  `~/miniforge3/envs/group-chat-market/bin/{flask,gunicorn,pytest}`. Or: `~/miniforge3/bin/conda run -n group-chat-market <cmd>`.
- Env `group-chat-market` is created from `environment.yml` (Python 3.12, Flask 3.1.3 + extensions, gunicorn, pytest). No other packages are available, so use only the standard library + these.
- cloudflared 2026.10.7: `~/.local/bin/cloudflared` (use the full path in systemd units).
- systemd **user** units go in `~/.config/systemd/user/`. Linger is enabled by Omar (`loginctl enable-linger`) so they run without a login session.
- git repo initialised on branch `main`; the GitHub repo is not yet created (Phase 1 step 3).
