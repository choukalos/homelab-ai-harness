# CHUCK — Tailscale plan (thor subnet router), built 2026-10-31

**Status: ON THE SHELF. Nothing is running. Safe to leave town — the files
below are inert until you deploy them, and nothing is exposed in the meantime.**

When you're ready (at home, or later via the cloudflared tunnel), it's a
**~15-minute job**: ~5 min in the Tailscale console, ~2 min on thor, then
verify. Full details in `tailscale/PLAN.md`; this is the short version.

## The design (one sentence)

Tailscale runs **only on thor** as a Docker container; thor advertises the
two LANs (`192.168.4.0/22`, `192.168.5.0/24`) as subnet routes, so from your
Mac (already on the tailnet) you can ssh to anything in the homelab when
you're out of town — no port forwarding, no public IP, no open router ports.

## The security split you asked for

Tailscale **routes, it doesn't NAT** — so thor can tell where traffic came
from by source IP, and LAN traffic never touches Tailscale at all:

| You're | Traffic path | Source IP thor sees | What's allowed |
|---|---|---|---|
| **At home** | straight over the LAN | `192.168.x.x` | **everything, unchanged** — ssh with passwords works exactly as today |
| **Out of town** | Mac → tailnet → thor → LAN | `100.64.0.0/10` | allowlist only: ssh (key-only) to thor/matrix, SMB/DSM to the NAS subnet. MySQL, Grafana, the LiteLLM API, etc. are **dropped** |

Same command both places (`ssh chuck@192.168.4.54`) — at home it goes over
Wi-Fi/Ethernet (password OK); away it goes through the tailnet (key only).

Two enforcers make the "away" side solid:
1. **nftables allowlist on thor** — the hard gate (survives reboots via systemd).
2. **sshd drop-in** — `Match Address 100.64.0.0/10` → key-only, no password.
   LAN sources don't match, so home stays simple.

## What's where

| File | What it is |
|---|---|
| `tailscale/PLAN.md` | **the master plan** — console steps, thor steps, tests, rollback |
| `tailscale/SECURITY.md` | the security model, layers, threat-model honesty |
| `tailscale/README.md` | node ops (logs, updates, re-auth) |
| `tailscale/docker-compose.yml` | the Tailscale node (independent compose project) |
| `tailscale/.env` | per-machine config; `TS_ROUTES` already set; **you paste the auth key here** |
| `tailscale/deploy-thor.sh` | **one-shot deploy**: hardening → container → waits for login |
| `tailscale/hardening/thor-tailnet.nft` | the port allowlist (the hard gate) |
| `tailscale/hardening/10-tailnet-sshd.conf` | key-only ssh from the tailnet |
| `tailscale/hardening/install-thor.sh` | installs the hardening (idempotent, validates first) |
| `tailscale/hardening/tailscale-tailnet-policy.service` | reboot persistence for the firewall |

## When you're ready — console (~5 min)

1. <https://login.tailscale.com> (choukalos@gmail.com). Note your tailnet
   domain (e.g. `choukalos.tail1234.ts.net`).
2. **Settings (gear) → Security → Generate an auth key** — expiry **1 hour**,
   **not reusable**. Copy the `tsha-...` (shown once).
3. *(after step B below)* thor appears in **Devices** → approve its
   advertised routes `192.168.4.0/22` + `192.168.5.0/24` (device page →
   Routes). **Until you approve, the tailnet can't reach the LAN** — this
   approval is your explicit "open the door" moment.
4. Optional extras (see SECURITY.md): ACL restricting which devices may use
   the subnets; Tailscale SSH (key-based, per-user).

## When you're ready — thor (~2 min)

```bash
cd ~/homelab/tailscale
nano .env              # TS_AUTHKEY=tsha-...
./deploy-thor.sh       # asks for sudo; hardening first, then the node
```

That's it. The script validates the nftables syntax before changing
anything, checks `sshd -t` before reloading ssh, and waits for the node to
log in (it'll tell you if the key was bad/expired).

## Then verify

```bash
# at home:
ssh chuck@192.168.4.54            # password still works (LAN path)
# away from home:
ssh chuck@192.168.4.54            # password REFUSED, key works (tailnet path)
nc -zv 192.168.4.54 3306          # refused — MySQL not reachable from tailnet
nc -zv 192.168.4.54 22           # allowed
```

## Honest caveats (read these, they're short)

- **The tailnet is the trust boundary.** A compromised *approved* device
  (your phone) reaches the allowlisted ports. The allowlist shrinks the
  blast radius; it doesn't remove device-level risk. Keep the tailnet small.
- **Thor is a single point of failure** for remote access (it's the only
  node). Acceptable for now; adding matrix as a second node later removes it.
- **The NASes have no tailnet-side firewall yet.** thor's allowlist gates
  what reaches them (SMB/DSM ports only), but adding the same sshd drop-in +
  a DSM firewall rule on the Synology is cheap defense-in-depth (notes in
  SECURITY.md).
- **If you ever open more ports in `thor-tailnet.nft`, you're widening the
  remote attack surface** — do it deliberately.

## Rollback (if you regret it)

```bash
cd ~/homelab/tailscale
docker compose down
sudo nft delete table inet tailnet_policy
sudo systemctl disable --now tailscale-tailnet-policy.service
sudo rm /etc/ssh/sshd_config.d/10-tailnet-sshd.conf && sudo systemctl reload ssh
# console: Devices → thor → ⋯ → Remove
```

## Later ideas (not needed for v1)

- matrix as a second tailnet node (redundancy; same compose file).
- Tailscale SSH on thor (no host sshd exposure at all).
- Synology/Lego NAS-side firewalls + sshd drop-ins.
- Tailscale ACLs once the tailnet has more than 2-3 devices.