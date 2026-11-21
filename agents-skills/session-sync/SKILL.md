---
name: session-sync
description: Ship the current pi session transcript to the homelab skill-runner for the reflection pipeline. Use when the user asks to sync/upload this session, or at session closeout when the user agrees.
---

# Session Sync

Upload the current pi session transcript to the homelab skill-runner
(`POST /api/sessions/ingest`) so the reflection pipeline sees this session.
Works on any pi that can reach thor (homelab and Mac). This skill only reads
the local session file and POSTs to the skill-runner — it never touches
other services.

## Remote mode (preferred — mcp_sessions, 2026-11-21)

If the `sessions_ingest` tool is available (the `mcp_sessions` server, routed
through the LiteLLM proxy — the only surface reachable from a remote
machine), use it: call `sessions_ingest` with the **verbatim transcript**
(raw .jsonl contents), the `session_id` (file basename without `.jsonl`),
and `host` (this machine's hostname). The server splits long transcripts
into ≤2 MiB parts automatically — **no base64, no curl, no manual
splitting, no 2 MiB bookkeeping**.

- `status: "stored"` → success. Report the part count + byte count.
- `status: "duplicate"` → already on the homelab (idempotent re-sync).
- `401`-style error → identity problem (key not mapped); fall back to the
  LAN curl path below if on the LAN, otherwise tell the user.
- Rate limit ~30 ingests/hour — batch at most a few sessions per hour.

Reading back: `sessions_get(session_id, line_start?, line_end?)` returns the
stored transcript (or a line slice) with a verifiable citation
(`session:{user_id}/{session_id}#L{start}-L{end}` / `#p{N}L{start}-L{end}`).
Content is capped at 512 KiB per call (413 above it) — page long
transcripts with narrow line ranges; `sessions_list()` shows what is
stored (metadata only).

The LAN curl path below remains as the fallback when the MCP tools are not
available (e.g. the proxy is down or this pi has no MCP access).

## Privacy rules (read first)

- **User-initiated only.** Never auto-upload mid-session, and never upload
  at closeout unless the user agreed to the `session-memory` closeout offer.
- **Warn once before the first upload** in a session: the transcript may
  contain personal content (e.g. medical voice notes) and will be stored on
  the homelab under the caller's **private** identity
  (`data/sessions/{user_id}/...`, mode 0600). Do not re-warn on later
  uploads in the same session.
- **If the user declines, refuse to upload** and remember the choice for
  the rest of the session — do not re-ask, do not upload.
- The transcript is always private to the caller. There is no household
  flag on this path.

## Workflow

1. **Locate the current session file.** Sessions live under
   `~/.pi/agent/sessions/<project-dir>/`, where the project dir is the cwd
   path with `/` replaced by `-` (e.g. `~/.pi/agent/sessions/--home-chuck-homelab--/`).
   The current session is the **most recently modified** `*.jsonl` in that
   directory (the file still being written to).
2. **Build the payload.**
   - `session_id` = the file's basename without `.jsonl`
     (e.g. `2026-11-06T13-30-04-455Z_01a1b10d-…`).
   - `host` = this machine's hostname (e.g. `macbook`, `thor.local`).
   - `started_at` / `ended_at` = ISO-8601 UTC (the file's mtime and the
     first/last entry timestamps are fine; the server truncates to 64
     chars).
   - `transcript` = the file's contents, verbatim.
   - `tags`: `["pi-session"]`.

   The transcript contains quotes and newlines — build the JSON with `jq`,
   never by hand-interpolating it into a shell string:

   ```bash
   jq -Rs --arg host "$HOST" --arg sid "$SID" \
     --arg start "$STARTED" --arg end "$ENDED" \
     '{host:$host, session_id:$sid, started_at:$start, ended_at:$end,
       transcript:., tags:["pi-session"]}' \
     "$SESSION_JSONL" > /tmp/session-sync-payload.json
   ```

3. **Upload.** The LiteLLM key comes from the environment / pi settings —
   **never print it**. The endpoint authenticates via the `X-Api-Key`
   header (the caller's own LiteLLM key; the admin key is rejected):

   ```bash
   curl -sS -X POST "http://<thor>:8091/api/sessions/ingest" \
     -H "X-Api-Key: $LITELLM_KEY" -H "Content-Type: application/json" \
     --data @/tmp/session-sync-payload.json
   ```

   `<thor>` = thor's LAN IP/hostname. From the Mac, the homelab LAN is
   reachable via the router OpenVPN; if unsure of the address, ask the user
   or `ping thor.local`.
4. **Report the result.**
   - `{"status":"stored", …}` → success. Report the sha256 prefix and byte
     count.
   - `{"status":"duplicate", …}` → already synced (idempotent re-sync).
     Report "already on the homelab".
   - `401` → bad/missing key, or the admin key was used. Tell the user to
     check the LiteLLM key; do not retry blindly.
   - `413` → transcript over the 2 MB cap — see the split convention below.
   - `400` → bad `session_id`/`host`/empty transcript. Fix and retry once.
   - Connection error / timeout → thor unreachable; the Mac is probably not
     on the homelab network.
5. **Clean up.** Remove `/tmp/session-sync-payload.json` after the upload
   (it contains the full transcript).

## Size cap and split convention

The server rejects transcripts above **2 MiB (2,097,152 bytes)** with `413`.
For longer sessions, split the jsonl on line boundaries into consecutive
chunks of ≤ ~1.5 MiB each and upload each part as `session_id.partN` —
e.g. `…_01a1b10d-….part1`, `…_01a1b10d-….part2`. The full `session_id`
(including the `.partN` suffix) must stay within 128 chars; pi session
basenames are 64 chars, so the suffix fits. Upload parts in order and
report how many parts were stored.

## Constraints

- Never print the LiteLLM key or the transcript contents in chat output.
- No auto-upload, ever — user-initiated only, with the one-time warning.
- No uploads on behalf of another identity — the transcript lands under
  the caller's own user_id.
- This skill never touches services other than the skill-runner session
  endpoints (via the `mcp_sessions` tools or the direct ingest route — no
  restarts, no reboots).