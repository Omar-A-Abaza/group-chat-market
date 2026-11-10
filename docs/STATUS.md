# Status (2026-11-10)

## Built
Full Phase 1 app per `docs/PLAN.md`: LMSR math (`app/market_math.py`), models, locked trading ops
(buy/sell/eliminate/resolve, no self-betting), auth, dashboard / market / leaderboard / profile pages with
Chart.js charts and a live buy/sell preview, an admin area (eliminate, resolve, reconfigure windows/odds/b
before trading, reset passwords), `flask seed` / `flask reset-password`, README, systemd unit files and
`deploy/start.sh` / `stop.sh`.

## Tested
- `pytest`: 22 passed (LMSR invariants, trading rules, payouts, elimination, auth, admin-only, CSRF, open redirect).
- Smoke test through Flask's test client on a throwaway DB: login, pages, buy, snapshots, admin eliminate/resolve, payout. All OK.
- `git ls-files` checked: no `.env`, `*.local.*` or `*.db` files tracked.
- `flask seed` ran against the real DB with the **example** accounts (alice admin, bob, carol, dave); passwords are in
  `passwords.local.txt` (git-ignored, chmod 600). Delete `instance/group_chat_market.db` and `passwords.local.txt` before
  seeding real names, or just add the real users.

## NOT done (blocked by the permission classifier)
- GitHub repo not created or pushed. Local commit `abafc8a` is ready: `gh repo create Omar-A-Abaza/group-chat-market --public --source . --push`
- systemd units not installed or started, and **no tunnel link**: run `bash deploy/start.sh`.
- LAN and mobile-data checks, and viewing the charts in a real browser, still need doing.
- Curl-with-cookie-jar smoke test was also blocked; the test client covered it instead.

## Next
Run the two commands above, create `accounts.local.toml` with the real names, run `flask --app wsgi seed`, hand out passwords, then refine the betting details.
