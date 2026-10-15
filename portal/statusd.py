#!/usr/bin/env python3
"""statusd — portal status publisher (sidecar of the portal container).

Publishes /status/status.json for the choukalos.com home page every
INTERVAL_SECONDS. The portal container serves /status/* read-only from the
same host directory (compose/compose.portal.yml), so no rebuild and no git
push is involved — the home page JS (js/status.min.*.js) picks up new data
on its next load.

Checks — Victoria Metrics first, direct probe as fallback:

  AI LAB      up{job="litellm"}                        -> GET $THOR_LITELLM/health/liveliness
  MEDIA       up{job="node-exporter-lego"}             -> GET http://$LEGO_IP:9100/metrics
  AUTOMATION  container_last_seen{id=~"/docker/$HOME_BRIDGE_ID.*",job="cadvisor-lego"}
                                                      > (time() - 120)
                                                      -> GET http://$LEGO_IP:8581/login
  PUBLIC FILES always "online" — if this file is being served, the portal is up.

State mapping (consumed by the home page JS): online | offline | unknown.
  - VM has data          -> 1 => online, else offline
  - VM has no data       -> direct probe decides: reachable => online, else offline
  - no VM query AND no probe (PUBLIC FILES) -> online by definition

If statusd itself dies, the file simply stops updating and the home page
shows "stale — last update" (staleness threshold is 5 min in the JS).

Security properties:
  - stdlib only, no shell, no network listeners, no credentials
  - read-only rootfs (compose); the only write is an atomic rename inside /runtime
  - all checks are unauthenticated health endpoints on the trusted LAN
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VM_URL = os.environ.get("VM_URL", "http://victoria-metrics:8428")
RUNTIME_ROOT = os.environ.get("PORTAL_RUNTIME_ROOT", "/runtime")
GIT_ROOT = os.environ.get("PORTAL_GIT_ROOT", "/git")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "30"))
TIMEOUT = float(os.environ.get("PROBE_TIMEOUT_SECONDS", "5"))

LEGO_IP = os.environ.get("LEGO_IP", "192.168.5.100")
THOR_LITELLM = os.environ.get("THOR_LITELLM", "http://thor-lan:4000")
# Homebridge container ID on lego (QNAP Container Station -> homebridge -> ID).
# Optional: when unset, AUTOMATION falls back to the direct HTTP probe only.
HOME_BRIDGE_ID = os.environ.get("HOME_BRIDGE_ID", "").strip()
# "Running" = cadvisor saw the container within this window (seconds).
# QNAP's cadvisor build labels containers by full 64-hex id only (no name
# label), so HOME_BRIDGE_ID may be a short prefix matched with a regex.
FRESH_WINDOW = 120

# (display name, VM query or None, fallback probe URL or None)
CHECKS = [
    ("AI LAB", 'up{job="litellm"}', THOR_LITELLM + "/health/liveliness"),
    ("MEDIA", 'up{job="node-exporter-lego"}', f"http://{LEGO_IP}:9100/metrics"),
    ("AUTOMATION",
     (f'container_last_seen{{id=~"/docker/{HOME_BRIDGE_ID}.*",job="cadvisor-lego"}}'
      f' > (time() - {FRESH_WINDOW})') if HOME_BRIDGE_ID else None,
     f"http://{LEGO_IP}:8581/login"),
    ("PUBLIC FILES", None, None),
]


def vm_value(query: str):
    """First sample value of a Victoria Metrics instant query, or None."""
    url = VM_URL + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        result = data.get("data", {}).get("result", [])
        if result:
            return float(result[0]["value"][1])
    except Exception as exc:  # noqa: BLE001 — any failure means "no data"
        print(f"vm query failed {query!r}: {exc}", file=sys.stderr)
    return None


def probe(url: str) -> bool:
    """True if the URL answers with a non-5xx status within TIMEOUT."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001 — unreachable == not up
        return False


def check(name: str, vm_query: str | None, fallback_url: str | None):
    """Return (state, source) for one light."""
    if name == "PUBLIC FILES":
        return "online", "hardcoded"
    if vm_query:
        value = vm_value(vm_query)
        if value is not None:
            return ("online" if value >= 1 else "offline"), "vm"
    if fallback_url:
        return ("online" if probe(fallback_url) else "offline"), "probe"
    return "unknown", "none"


def portal_revision() -> str | None:
    """Current git-sync commit (worktree dir name), or None while syncing."""
    try:
        return os.path.basename(os.readlink(os.path.join(GIT_ROOT, "current")))
    except OSError:
        return None


def publish(services: list[dict], revision: str | None) -> None:
    """Atomically write status.json (tmp + rename; readers never see partials)."""
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "services": services,
    }
    if revision:
        payload["portal_revision"] = revision
    body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    target = os.path.join(RUNTIME_ROOT, "status.json")
    tmp = os.path.join(RUNTIME_ROOT, ".status.json.tmp")
    with open(tmp, "wb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, target)


def main() -> None:
    print(
        f"statusd: interval={INTERVAL}s vm={VM_URL} lego={LEGO_IP} "
        f"homebridge_id={HOME_BRIDGE_ID or '(unset — probe only)'}",
        file=sys.stderr,
    )
    while True:
        started = time.monotonic()
        try:
            services = []
            for name, vm_query, fallback_url in CHECKS:
                state, source = check(name, vm_query, fallback_url)
                services.append({"name": name, "state": state})
                print(f"{name}: {state} ({source})", file=sys.stderr)
            publish(services, portal_revision())
        except Exception as exc:  # noqa: BLE001 — keep the loop alive
            print(f"publish cycle failed: {exc}", file=sys.stderr)
        time.sleep(max(1.0, INTERVAL - (time.monotonic() - started)))


if __name__ == "__main__":
    main()