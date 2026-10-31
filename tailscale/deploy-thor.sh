#!/usr/bin/env bash
# One-shot Tailscale deploy on thor: hardening first, then the node.
#
# Prereq: TS_AUTHKEY set in .env (console: Settings -> Security ->
#         Generate an auth key, short expiry, not reusable).
# Idempotent: safe to re-run (e.g. after rotating the key).
set -euo pipefail
cd "$(dirname "$0")"

# --- 0. preflight -----------------------------------------------------------
if ! grep -qE '^TS_AUTHKEY=tsha-' .env; then
  echo "ERROR: TS_AUTHKEY is not set in $(pwd)/.env"
  echo "Generate one: https://login.tailscale.com/admin -> Settings -> Security -> Generate an auth key"
  exit 1
fi
command -v docker >/dev/null || { echo "ERROR: docker not found"; exit 1; }

# --- 1. hardening (safe with or without the tailnet up) ----------------------
echo "==> [1/3] tailnet hardening (nftables allowlist + sshd key-only drop-in)"
./hardening/install-thor.sh

# --- 2. tailscale node --------------------------------------------------------
echo "==> [2/3] starting tailscale container"
docker compose up -d

# --- 3. wait for login --------------------------------------------------------
echo "==> [3/3] waiting for tailnet login (up to 90s)..."
ok=0
for i in $(seq 1 18); do
  if docker exec tailscale tailscale status >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 5
done
if [[ $ok -ne 1 ]]; then
  echo "ERROR: node not logged in after 90s — check the key (expired? wrong?)"
  docker logs --tail 30 tailscale
  exit 1
fi

echo
docker exec tailscale tailscale status
echo
echo "Deployed. Remaining steps (see PLAN.md):"
echo "  1. Console: approve the advertised subnet routes on thor's device page."
echo "  2. At home:  ping thor's tailnet IP; ssh chuck@192.168.4.54 (password OK)."
echo "  3. Away:     ssh chuck@192.168.4.54 (key only) + nc -zv 192.168.4.54 3306 (refused)."