# Tailscale — standalone VPN node

> **Chosen design: thor-only node + subnet router** — see [PLAN.md](PLAN.md)
> (master plan) and [SECURITY.md](SECURITY.md) (the security split). This
> README covers the node itself; `deploy-thor.sh` is the one-shot deploy.

One self-contained compose project that turns a machine into a Tailscale node.
**Same file on every machine** — it has its own `.env`, uses host networking,
and shares nothing (no networks, volumes, or env files) with the rest of the
homelab.

```
MacBook Air (already on tailnet)
      │  tailnet (WireGuard, NAT-traversal, no ports open)
      ├── thor    (192.168.4.54)  ← this box (the agent's host)
      ├── matrix  (192.168.4.55)
      ├── synology (NAS)
      └── lego-nas (192.168.5.100)
```

Result: from anywhere (phone, laptop, other tailnet device) you can
`ssh chuck@thor.<tailnet>` / `ssh chuck@matrix.<tailnet>` / reach the NAS
shares — no port forwarding, no public IP, no exposure.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | The node. Identical on all machines. |
| `.env` | Per-machine auth key (git-ignored). |

## 1. Admin panel (once, on your Mac or laptop)

1. Log in at <https://login.tailscale.com> (choukalos@gmail.com). Your tailnet
   name is shown at the top, e.g. `choukalos.tail1234.ts.net` — that's the
   MagicDNS domain; every node is reachable as `<name>.<tailnet>`.
2. **Generate an auth key per machine** (4 total: thor, matrix, synology,
   lego-nas):
   - Settings (gear) → **Security** → **Generate an auth key**
   - Expiry: 1 hour (or "one-time"). Do **not** make it reusable.
   - Copy the `tsha-...` value — it's only shown once.
3. Make sure **MagicDNS** is on (Settings → DNS, on by default).
4. When nodes appear in **Devices**, they auto-approve for the owner. If you
   enable the subnet-router option below, approve the advertised routes on
   the node's device page (or Settings → Access Controls).

## 2. Deploy on a machine

```bash
cd <this directory>          # copy this whole dir to the machine first
# 1. paste the machine's auth key:
nano .env                    # TS_AUTHKEY=tsha-...
# 2. (optional) set TS_HOSTNAME and/or TS_ROUTES in .env
# 3. start:
docker compose up -d
# 4. verify:
docker compose ps                      # "healthy"
docker exec tailscale tailscale status # "Logged in as ...", online peers
```

The `tailscale0` interface is created **on the host** (host networking), so
the machine itself is the node — sshd, SMB, etc. are all reachable at its
tailnet IP. State lives in the `ts-state` volume, so restarts/rebuilds keep
the same identity (same IP, same name).

### Per-machine notes

- **thor (192.168.4.54)** — this repo already has the directory at
  `homelab/tailscale/`.
- **matrix (192.168.4.55)** — `rsync -a tailscale/ matrix:tailscale/`, then
  the same 4 steps.
- **Synology** — needs the *Docker* (Container Manager) package. Drop the
  directory on the NAS (e.g. `docker/tailscale`), edit `.env`, then:
  `docker compose up -d` (DSM 7.2+ has the compose plugin; if not, install
  it or use the single-container fallback below). Host networking is
  supported by Synology Docker. Alternative: the Tailscale *Community
  package* for DSM (native app, no Docker) if you'd rather not run it in a
  container.
- **Lego NAS (192.168.5.100)** — if it runs Docker (Unraid, TrueNAS Scale,
  Proxmox LXC, ...), same 4 steps. If it can't run Docker, use the
  subnet-router option below so it's still reachable through thor.

Single-container fallback (any machine, no compose):

```bash
docker run -d --name tailscale --restart unless-stopped \
  --network host --cap-add NET_ADMIN --cap-add NET_RAW \
  --device /dev/net/tun \
  -v ts-state:/var/lib/tailscale \
  -e TS_AUTHKEY=tsha-... \
  -e TS_USERSPACE=false -e TS_ACCEPT_DNS=true \
  tailscale/tailscale:latest
```

## 3. Verify (from your Mac, which is already on the tailnet)

```bash
ping thor.<tailnet>          # tailnet IP, e.g. 100.x.y.z
ssh chuck@thor.<tailnet>     # normal sshd over the VPN
ssh chuck@matrix.<tailnet>
```

## 4. Optional: subnet router (reach the whole LAN)

Have thor advertise the LAN so *any* tailnet device can reach LAN hosts
(including NAS boxes that can't run Tailscale):

1. In `tailscale/.env` on **thor**: `TS_ROUTES=192.168.4.0/22,192.168.5.0/24`
   (adjust to your actual LANs), then `docker compose up -d`.
2. In the admin panel, approve the advertised routes on thor's device page.
3. From the Mac: `ssh chuck@192.168.5.100` (lego) etc. works directly.

**Security:** see [SECURITY.md](SECURITY.md) — the tailnet→LAN path is
allowlisted by an nftables policy on thor (ssh + NAS ports only) and sshd is
key-only for tailnet sources (`100.64.0.0/10`). At-home LAN usage, including
ssh with passwords, is completely unaffected.

## 5. Operations

- **Logs:** `docker logs tailscale` (daemon log: `ts-state` volume,
  `tailscaled.log1.txt`).
- **Update:** `docker compose pull && docker compose up -d` (identity is
  preserved via the `ts-state` volume).
- **Re-auth / rotate key:** `docker exec tailscale tailscale logout`, put a
  fresh key in `.env`, `docker compose up -d`. (Or interactively:
  `docker exec -it tailscale tailscale up` and open the printed URL.)
- **Remove a machine from the tailnet:** admin panel → Devices → ⋯ → Remove
  (deletes its key; the `ts-state` volume can then be wiped).
- **Healthcheck** = "connected to tailnet"; `unhealthy` means the node is
  logged out (expired key / removed) — check `docker logs tailscale`.

## Security notes

- Auth keys are one-time and short-lived; the key in `.env` is dead after
  first login. `.env` is git-ignored — never commit it.
- Nothing is exposed to the internet: Tailscale uses outbound-only
  WireGuard with DERP fallback; the router needs no port forwarding.
- Optional hardening: enable **Tailscale SSH** (admin panel → device →
  Settings → Tailscale SSH) so you can `ssh chuck@thor` even if host sshd is
  disabled.