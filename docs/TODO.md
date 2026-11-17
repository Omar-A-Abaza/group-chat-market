# TODO
- Cloudflare tunnel + systemd units: not started by the unattended run (the action was blocked by the permission
  classifier). Run `bash deploy/start.sh` yourself; it installs the units, starts them and prints the link.
- LAN check (http://192.168.1.96:8000) and mobile-data tunnel check not done; need a phone.
- Charts.js comes from a CDN: charts could not be viewed in a real browser here (only the JSON APIs and page HTML were tested).
- No login rate-limiting yet.
- Resolved markets lose per-user cost basis, so P/L after payout isn't shown on the profile.
- Blocked by the permission classifier during the unattended run, so **not done**: `gh repo create Omar-A-Abaza/group-chat-market --public --source . --push`
  (the local commit exists), and installing/enabling the systemd user units. Both are one-liners for you to run.
- Local env: the units and docs refer to a conda env named `group-chat-market`; locally it's reachable via a symlink in
  `~/miniforge3/envs/`. Recreate it properly with `conda env create -f environment.yml` when convenient.
- Rename the GitHub repo when it is created: `Omar-A-Abaza/group-chat-market`.
