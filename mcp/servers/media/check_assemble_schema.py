#!/usr/bin/env python3
"""Verify the live mcp_media MCP tool schema exposes the new media_assemble
quality params (upscale_each + text_overlays). Runs INSIDE the mcp_media
container (port 8000 is ai-net-only). Raw MCP JSON-RPC over SSE, stdlib only.
"""
import json
import sys
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


class SSEClient:
    """Minimal MCP SSE client (stdlib only)."""

    def __init__(self):
        self.messages_url = None
        self.responses = {}
        self._lock = threading.Lock()
        self._done = {}

    def _sse_loop(self):
        req = urllib.request.Request(BASE + "/sse",
                                     headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=600) as r:
            event = None
            data = None
            while True:
                line = r.readline().decode("utf-8", "replace").rstrip("\n")
                if not line:
                    event, data = None, None
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event == "endpoint":
                        self.messages_url = BASE + data
                        with self._lock:
                            self._done["endpoint"] = True
                    elif event == "message" and data:
                        try:
                            msg = json.loads(data)
                        except Exception:
                            continue
                        mid = msg.get("id")
                        if mid is not None:
                            with self._lock:
                                self.responses[mid] = msg
                                self._done[mid] = True

    def start(self):
        t = threading.Thread(target=self._sse_loop, daemon=True)
        t.start()
        deadline = time.time() + 30
        while time.time() < deadline:
            with self._lock:
                if self._done.get("endpoint"):
                    return self.messages_url
            time.sleep(0.05)
        raise RuntimeError("no SSE endpoint event within 30s")

    def _post(self, msg):
        req = urllib.request.Request(
            self.messages_url, data=json.dumps(msg).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=30).read()

    def rpc(self, method, params=None, timeout=60):
        mid = int(time.time() * 10000) % (10**12)
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        self._post(msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if mid in self.responses:
                    return self.responses[mid]
            time.sleep(0.1)
        raise TimeoutError(f"no MCP response for {method} within {timeout}s")

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._post(msg)


c = SSEClient()
print("SSE endpoint:", c.start())
c.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "schema-check", "version": "1.0"}})
c.notify("notifications/initialized")
tl = c.rpc("tools/list", {})
tools = {t["name"]: t for t in tl["result"]["tools"]}
print(f"total tools: {len(tools)}")

ma = tools.get("media_assemble")
if not ma:
    print("FAIL: media_assemble not found")
    sys.exit(1)
props = ma["inputSchema"]["properties"]

new_params = ["upscale_each", "upscale_resolution", "upscale_noise_scale",
              "upscale_fps", "upscale_seed", "text_overlays"]
print("\nmedia_assemble new quality params:")
missing = []
for k in new_params:
    present = k in props
    if not present:
        missing.append(k)
    default = props.get(k, {}).get("default", "<absent>")
    print(f"  {'PASS' if present else 'FAIL'}  {k:24s} default={default}")

old = ["shots", "vo", "music", "sfx", "width", "height", "fps",
       "vo_volume", "music_volume", "sfx_volume", "vo_start", "loudnorm"]
for k in old:
    if k not in props:
        print(f"  REGRESSION  {k} missing")
        missing.append(k)

desc = ma.get("description", "")
for feat in ["upscale_each", "text_overlays"]:
    if feat not in desc:
        print(f"  NOTE: description missing mention of {feat}")

print("\nRESULT:", "PASS" if not missing else f"FAIL {missing}")
sys.exit(1 if missing else 0)