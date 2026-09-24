#!/usr/bin/env python3
"""MCP-layer end-to-end test for the Qwen-Image-2.1 upgrade (run on thor).

Speaks raw MCP JSON-RPC over the mcp_media SSE endpoint (127.0.0.1:8000):
  1. initialize + tools/list — verify the new params are on the wire
     (generate_image: steps=25 default + model; edit_image: steps=25 +
     model + references)
  2. tools/call media_generate_image with DEFAULTS — proves the full MCP
     path runs the new qwen21 model and returns a GPU-host path.
  3. tools/call media_info on the result — verify dimensions.
"""
import json
import sys
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {detail}")


class SSEClient:
    """Minimal MCP SSE client (stdlib only)."""

    def __init__(self):
        self.messages_url = None
        self.responses = {}
        self._lock = threading.Lock()
        self._done = {}

    def _sse_loop(self):
        global line, event, data
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

    def rpc(self, method, params=None, timeout=1800):
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
            time.sleep(0.2)
        raise TimeoutError(f"no MCP response for {method} within {timeout}s")

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._post(msg)


c = SSEClient()
print("SSE endpoint:", c.start())

init = c.rpc("initialize", {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "qwen21-e2e-test", "version": "1.0"},
}, timeout=30)
check("initialize ok", "result" in init, f"({init.get('error')})")
c.notify("notifications/initialized")

tools = c.rpc("tools/list", timeout=30)["result"]["tools"]
byname = {t["name"]: t for t in tools}
check("18 tools over the wire", len(tools) == 18, f"({len(tools)})")

gi = byname.get("media_generate_image", {}).get("inputSchema", {})
check("wire: generate_image steps default 25",
      gi.get("properties", {}).get("steps", {}).get("default") == 25,
      f"({gi.get('properties', {}).get('steps')})")
check("wire: generate_image has model param",
      "model" in gi.get("properties", {}),
      f"({list(gi.get('properties', {}))})")

ei = byname.get("media_edit_image", {}).get("inputSchema", {})
check("wire: edit_image steps default 25",
      ei.get("properties", {}).get("steps", {}).get("default") == 25,
      f"({ei.get('properties', {}).get('steps')})")
check("wire: edit_image has model + references",
      "model" in ei.get("properties", {})
      and "references" in ei.get("properties", {}),
      f"({list(ei.get('properties', {}))})")

print("== tools/call media_generate_image (defaults -> qwen21) ==")
t0 = time.time()
res = c.rpc("tools/call", {
    "name": "media_generate_image",
    "arguments": {"prompt": "A cinematic keyframe of a lighthouse on a "
                            "stormy cliff at night, dramatic light, 35mm film"},
}, timeout=1800)
elapsed = time.time() - t0
print(f"   ({elapsed:.0f}s)")
payload = res.get("result", {})
content = payload.get("content", [{}])[0].get("text", "{}")
try:
    out = json.loads(content)
except Exception:
    out = {"raw": content}
print("   ", json.dumps(out)[:400])
check("mcp call returned a path",
      str(out.get("path", "")).startswith("/home/chuck/data/comfyui/run/media_jobs/"),
      f"({out})")
check("mcp call location=gpu_host", out.get("location") == "gpu_host", f"({out})")

if out.get("path"):
    info = c.rpc("tools/call", {
        "name": "media_info",
        "arguments": {"path": out["path"]},
    }, timeout=120)
    ic = info.get("result", {}).get("content", [{}])[0].get("text", "{}")
    try:
        idata = json.loads(ic)
    except Exception:
        idata = {}
    print("   info:", json.dumps(idata)[:200])
    check("mcp media_info 1280x720",
          idata.get("width") == 1280 and idata.get("height") == 720,
          f"({idata.get('width')}x{idata.get('height')})")

print(f"\n== RESULT: {ok} passed, {fail} failed ==")
sys.exit(1 if fail else 0)