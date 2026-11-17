# Roadmap

Ideas for later, roughly in the order they would be worth building.

## Notifications
Tell people when something happens that affects them: a market they hold resolves or is cancelled, a market
they created gets its first bet, a market closes soon, or someone replies in a thread they posted in.
Start with an in-app inbox (a bell with an unread count, backed by a `Notification` table written inside
the same transaction as `resolve` / `void_market`). Then add delivery channels: Web Push for phones, and an
optional webhook (Discord, Slack, Telegram) so a group can post results into its chat.

## Hosted demo
A public read-only instance with seeded fake data (`flask demo-data`), reset on a schedule, so anyone can
try the app without installing it.

## Portfolio and profile
- Profit/loss chart per user over time, and per-position return.
- Achievements: first win, best call (biggest return on a resolved market), hot streak, "contrarian"
  (won while betting against the crowd).

## Trading
- Limit orders ("buy Yes if it drops to 30c") and stop-outs, executed by the background job.
- Close-position button, and a "max you can safely bet" helper.

## Markets
- Categories / tags and a trending score on the dashboard.
- Edit a market's description and close time after creation (with an audit entry).
- Numeric range markets ("how many goals?") as a fourth kind.

## Seasons and admin
- Seasons: reset everyone's cash on a schedule and archive the leaderboard.
- Admin audit log (who resolved, cancelled, reset a password, created an invite).
- Per-group settings page (name, starting cash, liquidity) instead of editing `.env`.

## Platform
- Read-only public JSON API with documented endpoints.
- Move the lock into the database and support Postgres, so more than one worker can run.
- Stable custom domain with a named Cloudflare tunnel.
