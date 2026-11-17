# Architecture

## Overview

A small server-rendered Flask app. One process serves HTML (Jinja), a few JSON endpoints that feed the
charts and the live bet preview, and a background thread that closes markets and expires date windows.
State lives in a single SQLite file. There are no external services.

```
browser ── HTML / JSON ──► Flask (views, auth, admin) ──► trading.py (one lock) ──► market_math.py
                                         │                                              (pure functions)
                                         └──► SQLAlchemy ──► SQLite
background thread ──► trading.close_expired_markets / auto_eliminate_expired (every 5 min)
```

## Pricing (LMSR)

Markets use Hanson's logarithmic market scoring rule, an automated market maker, so users trade against
the market itself rather than waiting for a matching counterparty.

For a market with `N` live options, share counts `q_i` and liquidity `b`:

- cost function `C(q) = b · ln( Σ e^(q_i / b) )`
- price of option `i`: `p_i = e^(q_i / b) / Σ e^(q_j / b)`, so prices are positive and sum to 1
- buying `$X` of option `i` yields `Δ = b · ln( S·(e^(X/b) − 1) + e^(q_i/b) ) − q_i` shares, where `S = Σ e^(q_j/b)`.
  This closed form comes from solving `C(q + Δ·e_i) − C(q) = X`, so no numeric search is needed.
- selling `s` shares refunds `C(q) − C(q − s·e_i)`
- each share of the winning option pays `$1`

All of it is computed with a log-sum-exp shift so large share counts don't overflow
(`app/market_math.py`; see `test_numerically_stable_large_q`). Starting odds `p_i` are set with
`q_i = b · ln p_i`. Eliminating an option removes it from the sum, so the rest renormalise to 100%.
The market maker's worst-case loss is `b · ln N` per market, which doesn't matter with play money.

`b` is the liquidity: a higher value means a given bet moves the odds less.

Money and shares are floats, displayed to the cent; the tests check the invariants (prices sum to 1,
buy-then-sell returns the money, the closed form matches the cost difference).

## Data model

| Table | Purpose |
|---|---|
| `User` | username, display name, password hash, admin flag, cash |
| `Invite` | signup link: token, optional expiry and max uses, revoked flag |
| `Market` | title, description, kind (`yes_no`, `multiple_choice`, `date_windows`), liquidity `b`, status, close time, creator, optional restricted user, winner, resolution note |
| `Outcome` | an option: label, share count `q`, `eliminated`, optional `ends_on` (date windows) |
| `Position` | user's shares in an option plus cost basis (for profit/loss) |
| `Trade` | immutable log: buy, sell, payout, refund (also drives volume and the activity feed) |
| `PriceSnapshot` | market prices after every change, for the odds chart |
| `NetWorthSnapshot` | every user's net worth after every trade, for the leaderboard chart |
| `Comment` | discussion per market |

## Market lifecycle

```
open ──(close time passes)──► closed ──► resolved   (winner pays $1/share)
  │                              │
  └──────────────────────────────┴────► void       (everyone refunded buys − sells)
```

- Trading is allowed only while `open`. A `closed` market can still be resolved or cancelled.
- The market's **creator** manages it (resolve, cancel, eliminate an option, edit options before the first
  trade). An **admin** can do the same so a market can't get stuck if its creator disappears.
- **Date-window** markets have an end date per option. When it passes, the option is eliminated
  automatically: its holders lose those shares and the remaining odds rescale. The last live option is never
  eliminated, and the open-ended final option never expires.
- A **cancelled** market refunds each user the sum of their buys minus their sells in it, so everyone ends
  up exactly where they started.

## Concurrency

All money-moving operations (`buy`, `sell`, `resolve`, `void_market`, eliminations, the scheduler) take one
process-wide re-entrant lock, re-read the user inside it, and commit or roll back as a unit. That is enough
for a single gunicorn worker with several threads, which is why the docs insist on one worker. Scaling out
would mean moving the lock into the database (`SELECT … FOR UPDATE` on Postgres, or an explicit write
transaction) and the rate limiter into shared storage.

## Security model

- Passwords are hashed with Werkzeug (salted PBKDF2/scrypt); minimum length 8.
- CSRF protection on every state-changing request (Flask-WTF); the JS endpoints used by the page are `GET` only.
- Login throttling: 5 failures per (IP, username) per 10 minutes, then HTTP 429 until the window passes.
  (Behind a reverse proxy, configure it to forward the client address so the limit is per client.)
- Invite tokens are random (`secrets.token_urlsafe`), can expire, have a use limit, and can be revoked.
- The first-run setup page only works while there are no users.
- Open-redirect protection on the post-login `next` parameter; user-supplied text is escaped by Jinja.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` when `SESSION_COOKIE_SECURE=1`.
- Read-only pages (markets, odds, leaderboard) are public by design; anything that changes state needs a login.

## Front end

Plain HTML/CSS/JS, no build step. `style.css` defines design tokens (colour, radius, spacing) with light and
dark themes; `app.js` handles the theme toggle, toasts, local-time rendering, the bet panel with debounced
live preview, and a small SVG line-chart renderer with range buttons (1 day / 1 week / all), top-N
filtering and tap-to-highlight. Times are stored in UTC and shown in the viewer's timezone.

## Testing

`pytest` runs against an in-memory SQLite database with CSRF disabled (and one test with it on). Fixtures
build users and markets; tests cover the maths, every trading rule, the lifecycle (close, resolve, cancel,
auto-expiry), access control, invites, rate limiting, validation, and the main HTTP flows.
