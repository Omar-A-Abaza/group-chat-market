# Group Chat Market

A fake-money prediction market for a group chat. Everyone starts with $1,000. Each friend has a market,
"When will <name> get married?", with date-window outcomes. Buy shares in the window you believe in;
the odds move live. No betting on your own market.

## Setup
```
conda env create -f environment.yml && conda activate group-chat-market
cp .env.example .env        # set SECRET_KEY
cp accounts.example.toml accounts.local.toml   # real names (git-ignored)
flask --app wsgi seed       # creates users + markets; passwords go to passwords.local.txt (git-ignored)
flask --app wsgi reset-password <user>
pytest
gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8000 wsgi:app
```
Keep gunicorn at **one worker**: the trade lock is in-process.

## Betting math in plain English
Prices come from an LMSR market maker with liquidity `b` (default 250). Each window has a share count;
a window's price is its share of the total, and all prices add to 100%. Buying makes your window's
price rise, so the more you buy, the worse the average price. Each winning share pays $1.
Selling returns what the market maker would charge to move back. Net worth = cash + shares × price.
Fake money, so the house subsidy (at most `b·ln N` per market) doesn't matter.

## Admin
`/admin`: eliminate a window that passed unmarried (its shares become worthless, others rescale to 100%),
resolve a market to the winning window (pays $1/share), reset passwords, and, before any trade, edit
windows, starting odds (`Label | percent` per line) and `b`.

## Start/stop
`deploy/start.sh` installs the systemd **user** units (gunicorn on :8000 and a Cloudflare quick tunnel),
starts them and prints the tunnel link; `deploy/stop.sh` stops them. Quick-tunnel URLs change on restart.
Set `SESSION_COOKIE_SECURE=1` in `.env` if you only use the HTTPS tunnel link.
