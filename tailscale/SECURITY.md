# Tailnet security model (subnet-router design)

Design: **Tailscale runs only on thor** (the `tailscale/` compose project),
and thor advertises the LANs (`192.168.4.0/22`, `192.168.5.0/24`) as subnet
routes. Every other machine is reached *through* thor's routing.

## Why at-home stays simple and remote gets hardened

Tailscale **routes, it does not NAT**. So on thor:

| Traffic | Source IP seen by thor | Policy |
|---|---|---|
| At home, Mac → thor/NAS over LAN | `192.168.x.x` | **Unchanged** — ssh/password works exactly as today |
| Away, Mac → thor/NAS via tailnet | `100.64.0.0/10` (v4) / `2600:1c00::/8` (v6) | Allowlisted: ssh key-only, NAS ports only |

Your Mac picks the path automatically: at home it has a directly-connected
route to `192.168.4.0/22` (Wi-Fi/Ethernet) and never touches Tailscale for
LAN IPs; away, the tailnet route (via thor) is the only way in. Same command
both places: `ssh chuck@192.168.4.54` — different path, different policy.

## The layers

1. **Tailnet membership** (biggest win). Only devices you approve can
   connect. Tailscale is outbound-only (UDP 41641, DERP fallback) — **no
   ports are opened on your router**, nothing inbound from the internet
   exists. A stranger on the internet has zero path to your LAN.
2. **nftables allowlist on thor** (`hardening/thor-tailnet.nft`) — the hard
   gate for all tailnet→thor and tailnet→LAN traffic. From the tailnet:
   ssh (22) to thor/matrix, SMB (139/445) + DSM web (5000/5001) to the NAS
   subnet. Everything else (MySQL 3306, Grafana, the LiteLLM API, all the
   `0.0.0.0` listeners) is dropped. LAN traffic is never matched.
3. **sshd drop-in** (`hardening/10-tailnet-sshd.conf`) — from
   `100.64.0.0/10` only: `PasswordAuthentication no`, key-only. LAN sources
   don't match → at-home password ssh unchanged. Install the same file on
   matrix and the NASes.
4. **Tailscale ACL** (admin panel, optional) — restrict *which* tailnet
   devices may use the subnet routes, and on which ports. Softer layer
   (enforced per-node); the firewall above is the one that actually bites.
   Matters more once you add more devices to the tailnet.
5. **Optional: Tailscale SSH** — enable per device (panel → device →
   Settings → Tailscale SSH) for key-based ssh with per-user controls and no
   host sshd exposure at all.

## Install (on thor)

```bash
cd homelab/tailscale/hardening
./install-thor.sh        # asks for sudo; validates before changing anything
```

It loads the nftables table, installs the sshd drop-in (with `sshd -t`
validation before reload), and enables a systemd unit so the policy survives
reboots. Re-run it any time after editing the files.

## Tailscale ACL (panel → Settings → Access Controls)

Default is all-accept. To restrict subnet access to your own devices:

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["<YOUR_MAC>", "<YOUR_PHONE>"],
      "dst": ["192.168.4.0/22", "192.168.5.0/24"]
    },
    {
      "action": "accept",
      "src": ["<YOUR_MAC>", "<YOUR_PHONE>"],
      "dst": ["autogroup:member"]
    }
  ],
  "ssh": []
}
```

(Use exact device names from the Devices page. First match wins; anything
not accepted is denied. If you keep the default ACL, that's fine — the
thor firewall is the enforcement layer.)

## NAS-side (defense in depth)

- **Synology:** Control Panel → Security → Firewall: allow
  `100.64.0.0/10` only for the ports you use (or block it entirely and rely
  on thor's allowlist). Same sshd `Match Address 100.64.0.0/10` drop-in for
  DSM's sshd.
- **Lego NAS:** same idea if it has a firewall/sshd.

## Honest threat model

- The tailnet **is** the trust boundary: a compromised *approved* device
  (your phone, a laptop) reaches whatever the allowlist permits. The layers
  above shrink the blast radius (ports, key-only auth) but don't remove
  device-level risk. Keep the tailnet small, use short-lived auth keys, and
  consider Tailscale SSH.
- **Single point of failure:** thor is the only tailnet node — if it's down,
  remote access is down. Acceptable for now; adding matrix as a second node
  later removes it.
- Subnet routes make the whole LAN reachable from the tailnet *in principle*;
  the firewall allowlist is what keeps it to ssh + NAS. If you open more
  ports in the `.nft`, you're widening the remote attack surface — do it
  deliberately.