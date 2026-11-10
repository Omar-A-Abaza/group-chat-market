#!/usr/bin/env bash
# Install units (if needed), start both services, print the tunnel link.
set -e
D="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.config/systemd/user
cp "$D"/group-chat-market.service "$D"/cloudflared.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now group-chat-market.service cloudflared.service
systemctl --user restart cloudflared.service   # a restart gives a fresh quick-tunnel URL
for i in $(seq 1 30); do
  url=$(journalctl --user -u cloudflared.service --since "2 min ago" --no-pager 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)
  [ -n "$url" ] && { echo "Tunnel: $url"; exit 0; }
  sleep 1
done
echo "Tunnel link not found yet; check: journalctl --user -u cloudflared.service"
