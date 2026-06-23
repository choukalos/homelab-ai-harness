# Siri Shortcut for Homelab AI access

Unified Siri/CarPlay gateway for the homelab AI harness. Routes voice/text
commands to the appropriate backend service (research, image generation,
demo creation, etc.) and rewrites all media URLs to public-facing endpoints.

---

## Demo Listing & Search

Siri can list and search all demos from a unified `demos/` directory:

| Voice Command | Intent | Behavior |
|---|---|---|
| "list my demos" / "show my demos" | `list_demos` | Returns all demos (workflow + simple) with public URLs |
| "find demo about X" / "demo for X" | `find_demo` | Searches title, description, tags across all demo types |
| "create a demo..." / "build a demo..." | `create_demo` | Kicks off the full 8-phase pipeline (fire-and-forget) |
| "html demo..." / "prototype..." | `demo` | Instant one-click demo via `pm_demo.service` |

Both **workflow demos** (subdirectories with `metadata.json`) and **simple
demos** (flat `.html` files) are scanned by `_scan_all_demos()` for a
unified list. All URLs returned are public-facing (`PUBLIC_BASE_URL`).

---

# Apple Shortcuts flow
Dict:
  text = Dictated Text
  mode = voice
  return_media = true

Get Contents of URL:
  URL: https://siri.yourdomain.com/siri/chat
  Method: POST
  Headers:
    Content-Type: application/json
    X-Harness-Api-Key: your-key
    CF-Access-Client-Id: ...
    CF-Access-Client-Secret: ...
  Body: JSON

Get Dictionary Value: speak
Speak Text
