#!/usr/bin/env bash
# Install the tailnet ingress hardening on thor (idempotent).
#   - nftables allowlist: tailnet (100.64.0.0/10) -> thor/LAN, restricted ports
#   - sshd drop-in: key-only from the tailnet; LAN keeps password auth
#   - systemd unit so the firewall survives reboots
set -euo pipefail
cd "$(dirname "$0")"

echo "[0/5] syntax check (aborts before changing anything if bad)"
sudo nft -c -f thor-tailnet.nft
echo "      nftables syntax OK"

echo "[1/5] nftables policy -> /etc/tailscale/"
sudo mkdir -p /etc/tailscale
sudo cp thor-tailnet.nft /etc/tailscale/

echo "[2/5] sshd drop-in -> /etc/ssh/sshd_config.d/"
sudo cp 10-tailnet-sshd.conf /etc/ssh/sshd_config.d/
sudo sshd -t
echo "      sshd config OK"

echo "[3/5] systemd unit (reboot persistence)"
sudo cp tailscale-tailnet-policy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tailscale-tailnet-policy.service

echo "[4/5] activating firewall"
sudo systemctl restart tailscale-tailnet-policy.service

echo "[5/5] reloading sshd"
sudo systemctl reload ssh

echo
echo "Done. Verify:"
echo "  nft list table inet tailnet_policy | head"
echo "  sshd -T | grep -A3 'match address 100.64.0.0/10'"
echo "  (test from the tailnet once the tailscale container is up:"
echo "   ssh chuck@thor.<tailnet>  -> key only, password refused)"