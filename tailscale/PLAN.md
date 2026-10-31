# Tailscale plan — subnet router on thor

One shot, ~15 minutes total. Nothing here is running yet; every step is
optional until you run it. If you leave town before doing this, nothing is
exposed and nothing breaks — the files below are inert until deployed.

```
MacBook Air (already on tailnet)
      │  tailnet — outbound-only WireGuard, no ports opened on your router
      ▼
   thor  (the ONLY machine running Tailscale; this box)
      │  subnet routes: 192.168.4.0/22 + 192.168.5.0/24 (approved in console)
      ▼  allowlisted by nftables: ssh + NAS ports only, key-only ssh
   matrix (192.168.4.55) · NASes (192.168.5.0/24) · rest of LAN
```

**Result:** away from home, `ssh chuck@192.168.4.54` / `ssh chuck@192.168.4.55`
/ SMB to the NASes all work through the tailnet. At home, LAN usage is
byte-for-byte unchanged (ssh with passwords included) — see SECURITY.md for
why (Tailscale routes without NAT, so tailnet traffic is identifiable by its
`100.64.0.0/10` source and gets the strict policy; LAN traffic never matches).

---

## Step A — Tailscale console (~5 min, from your Mac)

1. Open <https://login.tailscale.com> (choukalos@gmail.com).
2. Note your **tailnet domain** (shown on the Devices page, e.g.
   `choukalos.tail1234.ts.net`) — used in the tests below.
3. **Generate an auth key** (this is the only "add device" action you need):
   - Settings (gear) → **Security** → **Generate an auth key**
   - Expiry: **1 hour** · Reusable: **off** · tags: skip
   - Copy the `tsha-...` value — shown only once.
4. *(After Step B, when thor appears in Devices)* **approve the subnet
   routes**: thor's device page → **Routes** → approve
   `192.168.4.0/22` and `192.168.5.0/24` (or Settings → Access Controls).
   Until you approve them, the tailnet can reach thor itself but **not**
   the LAN — approval is your explicit "open the door" moment.
5. Optional hardening (see SECURITY.md):
   - **ACL** (Settings → Access Controls): restrict which devices may use
     the subnets — template in SECURITY.md.
   - **Tailscale SSH** (thor device page → Settings → Tailscale SSH):
     key-based ssh with per-user controls, no host sshd exposure.

That's the whole console job. MagicDNS is on by default — no other
settings needed. Your Mac needs no changes (it accepts subnet routes
automatically; if a LAN IP doesn't resolve later, check its Tailscale app →
Settings → "Accept subnet routes").

## Step B — Thor (~2 min)

```bash
cd ~/homelab/tailscale

# 1. paste the key from Step A:
nano .env                # TS_AUTHKEY=tsha-...

# 2. one-shot deploy (hardening first, then the container, waits for login):
./deploy-thor.sh
```

The script does, in order:
1. **nftables allowlist** (`hardening/thor-tailnet.nft` → systemd unit,
   reboot-safe) — tailnet→thor: port 22 only; tailnet→LAN: 22 to matrix,
   139/445/5000/5001 to the NAS subnet; everything else from the tailnet
   dropped. LAN traffic untouched.
2. **sshd drop-in** (`hardening/10-tailnet-sshd.conf` →
   `/etc/ssh/sshd_config.d/`) — from `100.64.0.0/10`: key-only, no
   password. LAN sources don't match → at-home password ssh unchanged.
3. **tailscale container** (`docker compose up -d`) with
   `TS_ROUTES=192.168.4.0/22,192.168.5.0/24` (already in `.env`), then
   waits for the node to log in and prints its status.

If you're **away** and decide to do it later: ssh to thor through your
existing cloudflared tunnel, then run the same two steps.

## Step C — Verify

At home (tailnet path, from the Mac):

```bash
docker exec tailscale tailscale ip        # thor's 100.x tailnet IP
ping <that 100.x IP>                       # tailnet works
ssh chuck@192.168.4.54                     # LAN path — password still works
```

Away from home (or on a different network) — the real test:

```bash
ssh chuck@192.168.4.54        # goes via tailnet: password REFUSED, key OK
ssh chuck@192.168.4.55        # matrix, same
smb://192.168.5.100           # NAS reachable
# firewall spot-check (should be refused):
nc -zv 192.168.4.54 3306      # MySQL — dropped from tailnet
nc -zv 192.168.4.54 22       # ssh — allowed
```

## If you change your mind / tear it down

```bash
cd ~/homelab/tailscale
docker compose down                      # remove the node (console: remove device)
sudo nft delete table inet tailnet_policy
sudo systemctl disable --now tailscale-tailnet-policy.service
sudo rm /etc/ssh/sshd_config.d/10-tailnet-sshd.conf && sudo systemctl reload ssh
```

Console: Devices → thor → ⋯ → Remove (deletes its key).

## File map

| File | Role |
|---|---|
| `PLAN.md` | this document |
| `docker-compose.yml` + `.env` | the Tailscale node (thor only) |
| `deploy-thor.sh` | one-shot deploy (hardening + node + login wait) |
| `hardening/thor-tailnet.nft` | the port allowlist (hard gate) |
| `hardening/10-tailnet-sshd.conf` | key-only ssh from the tailnet |
| `hardening/tailscale-tailnet-policy.service` | reboot persistence |
| `hardening/install-thor.sh` | installs the hardening (idempotent) |
| `SECURITY.md` | the model, layers, threat-model honesty |
| `README.md` | node ops (logs, updates, re-auth) |