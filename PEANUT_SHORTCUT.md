# 🥜 Peanut — Siri Shortcut Guide

> **Peanut** (named after the dog) is the family's Siri voice into the
> homelab AI brain: a local LLM, the family knowledge base, per-person
> memory, web search, and the media/demo pipelines.
>
> Say **"Hey Siri, Peanut"** and ask anything. This guide builds the
> shortcut (MVP → post-MVP) and shows how to add family members.
>
> Machine-facing API reference: [README_SIRI.md](./README_SIRI.md).

---

## What's under the hood (30 seconds)

```
iPhone Siri ──► Shortcut ──► POST https://siri.choukalos.com/siri/api/chat
                              (X-API-Key: <your key>)
                        ──► skill-runner (AI harness)
                              ├── chat:        local LLM (matrix-coder) + your memory
                              ├── siri-chat:   + family KB, web search, homelab status
                              └── media/demo:  GPU pipelines → public image/demo URLs
```

- **`speak`** = what Siri reads aloud (short, ≤ ~250 chars)
- **`display`** = full answer (shown on screen)
- **`links`** = list of public URLs (research sources, demos)
- **`media`** = public URL of a generated image
- **`job_id`** = present when the task is long-running (poll it)

Your key (`LITELLM_KEY_CHUCK` / `LITELLM_KEY_DYLAN` in `.env`) is what the
shortcut sends in the `X-API-Key` header. It's also what makes Peanut's
**memory** per-person (chuck's memories ≠ dylan's memories).

---

# Part 1 — MVP Shortcut (spoken answers)

**Goal:** "Hey Siri, Peanut" → Peanut asks your question → Peanut answers
out loud. ~10 minutes, one-time.

> ### ⚠️ Platform gotcha: `Send HTTP Request` is missing on some Macs
> The macOS Shortcuts action library is a **subset** of the iPhone's — the
> `Send HTTP Request` action does **not exist on macOS** (as of macOS Tahoe
> 26.6.2; it's an iOS/iPadOS action). That's why you couldn't find it.
>
> **The plan:** build the shortcut on your **iPhone** (10 min, below). It
> syncs to your Mac via iCloud (the Mac copy can't run it — the HTTP action
> is unavailable there — but it's a handy reference copy). If you want a
> working shortcut on the Mac too, see **§1.4** (a Mac-only variant that
> uses `Run Shell Script` + `curl` instead).
>
> ### ⚠️ Action names: Mac vs iPhone
> The Mac app calls the text-input action **`Ask for Input`** — on iPhone
> the same action shows up as **`Ask for Text`**. All other actions keep
> their names on both platforms. If you can't find an action, type its name
> in the **search field** of the action library.

## 1.1 Create the shortcut (on your iPhone)

1. Open the **Shortcuts** app on your iPhone → **+** (top right) → **New Shortcut**.
2. Name it **`Peanut`**.
   - Siri triggers a shortcut by its **exact name**: "Hey Siri, Peanut".
   - If "Peanut" (a common word) ever mis-triggers, rename it **`Ask Peanut`**
     and use "Hey Siri, Ask Peanut".
3. Tap **Add Action** and add the following, **in order** (search for each
   bold name):

### Action 1 — `Ask for Text`
*(iOS 18+. On older iOS use **Dictate Text** instead.)*
- **Prompt Text:** `What do you want to ask Peanut?`
- This captures your spoken question (when triggered by Siri) or typed
  question (when run from the app).

### Action 2 — `Text`
*(builds the JSON request body — Shortcuts can't build JSON natively)*
- Type exactly:
  ```
  {"text": ""}
  ```
- Delete the empty `""` and tap the **`Ask for Text` variable chip**
  (top of the screen) so it reads:
  ```
  {"text": "[Ask for Text]"}
  ```

### Action 3 — `Send HTTP Request`
- **URL:** `https://siri.choukalos.com/siri/api/chat`
- **Method:** `POST`
- **Headers** → tap **Add Header**:
  - Name: `X-API-Key`
  - Value: *your key* (`sk-…` — from `.env` on the homelab, or send it to
    yourself via Messages from the Mac. **Do not put it in a note anyone else
    can see.**) 
- **Body** → tap **Add Body** → type: `JSON`
  - **Body:** tap the variable bar and select the **`Text`** action's output
    (the `{"text": …}` variable).
- *(Show More → Timeout: leave the default; sync answers usually come back in
  < 15 s.)*

### Action 4 — `Get Dictionary Value`
- **Key:** `speak`
- **From:** the `Send HTTP Request` result (auto-selected).

### Action 5 — `Speak Text`
- Input: the `Get Dictionary Value` result.
- **This is the whole MVP.** Peanut now talks.

### Action 6 (optional) — `Show Result`
- Input: add a `Get Dictionary Value` for key `display` first, then show it.
- Gives you the full answer on screen while Siri speaks the short version.

4. **Add to Siri:** tap the **⋯** menu next to the shortcut → **Add to Siri**
   (hold the on-screen button to confirm).
   - Or: Settings → Siri & Search → "Hey Siri, Peanut".

## 1.2 Test it

1. Tap the **▶ Run** button in the Shortcuts app — a dialog asks for your
   question (type it), and Peanut answers out loud.
2. Then say **"Hey Siri, Peanut"** — the same shortcut prompts you to
   **speak** your question instead.

| You say | What happens |
|---|---|
| "Hey Siri, Peanut" → *what time is it in Chicago?* | Fast spoken answer (default `chat` intent — direct LLM, no tools) |
| "Hey Siri, Peanut" → *remember that the garage door code is 4415* | `remember` intent → stores it in **your** memory ("Got it — I'll remember that.") |
| "Hey Siri, Peanut" → *what did I tell you about the garage door?* | LLM answers from your retrieved memories |

**On the Mac:** the shortcut syncs over and shows up in the Mac Shortcuts
app, but it can't run there (the `Send HTTP Request` action doesn't exist on
macOS). For a working Mac version, see **§1.4**.

## 1.3 What you can ask (intent cheat sheet)

The harness auto-detects intent from your words:

| Say something like… | Intent | Sync? |
|---|---|---|
| *(anything else)* | `chat` — plain LLM chat + your memory | ✅ instant |
| "Remember that …" / "Please note …" | `remember` | ✅ |
| "Forget …" | `forget` | ✅ |
| "Generate an image of …" | `media-generate` | ✅ 30–90 s (GPU) |
| "Siri chat …" / "Siri ask …" | `siri-chat` — **family KB + web search + homelab status** | ⏳ async |
| "Research brief on …" | `research-brief` | ⏳ async |
| "Deep research …" | `deep-research` | ⏳ minutes |
| "Create a demo …" | `create-demo` | ⏳ 2–5 min |
| "Make a presentation about …" | `build-presentation` | ⏳ 3–5 min |
| "List my demos" / "Find demo …" | `list-demos` / `find-demos` | ⏳ seconds |
| "List my images" | `list-images` | ⏳ seconds |
| "Morning brief" | `morning-brief` | ⏳ 30–60 s |
| "Investment brief" | `investment-brief` | ⏳ 30–60 s |

**MVP note:** async intents return *"I've started processing …"* immediately
and give a `job_id`. The MVP shortcut just speaks that. Part 2 adds the
polling so you get the actual result.

## 1.4 (Optional) Mac version: `Run Shell Script` + `curl`

macOS has no `Send HTTP Request` action, but it **does** have
**`Run Shell Script`** — and `curl` is built in. This gives you a
**Mac-only** shortcut (name it **`Peanut Mac`** so it doesn't clash with the
iPhone one — trigger: "Hey Siri, Peanut Mac").

1. New shortcut → name it **`Peanut Mac`**.
2. Add **`Ask for Input`** (Mac name for "Ask for Text") — prompt:
   `What do you want to ask Peanut?`
3. Add **`Run Shell Script`** → paste this (replace `<PASTE_KEY>` with your
   key) → check **"Pass input: as arguments"**:
   ```bash
   #!/bin/bash
   QUESTION="$*"
   ESCAPED=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$QUESTION")
   curl -s --max-time 60 -X POST https://siri.choukalos.com/siri/api/chat \
     -H "Content-Type: application/json" \
     -H "X-API-Key: <PASTE_KEY>" \
     -d "{\"text\": $ESCAPED}" | \
   python3 -c 'import json,sys
   d=json.load(sys.stdin)
   print(d.get("speak") or d.get("display") or "Peanut got no answer.")'
   ```
   The script does the whole job: JSON-escapes your question, POSTs it,
   and prints just the `speak` text.
4. Add **`Speak Text`** — input: the script's output.

**Notes:**
- Requires `python3` (Xcode Command Line Tools — macOS will prompt
  `xcode-select --install` the first time if you don't have them).
- macOS will ask permission to run the script the first time → **Allow**.
- Your key lives in the script body — visible only to you on your Mac.
- This variant is **Mac-only** (`Run Shell Script` doesn't exist on
  iPhone) — the synced copy on your iPhone won't run.
- To extend it later (links/media, Part 2), have the script print the
  `links`/`media` values too and add `Add to Reminders` after `Speak Text`.

---

# Part 2 — Post-MVP: links, media & CarPlay

**Goal:** when Peanut produces something (an image, research sources, a
demo), the **links land somewhere you can open later — including from
CarPlay while driving.**

## 2.1 Where links come from

| Intent | What's in the response |
|---|---|
| `media-generate` | `media` = public image URL (sync) |
| `siri-chat`, `research-brief`, `deep-research`, demos, presentations | `job_id` → the finished job's `summary`/artifact carries the answer + links (async) |

Media URLs are public: `https://siri.choukalos.com/media/files/…` — anyone
with the URL can open them (no auth). Don't generate sensitive images.

## 2.2 The "Peanut Links" store: Reminders

**Reminders is the CarPlay-friendly inbox** — it's a first-class CarPlay app,
Siri can read it hands-free, and links open in Safari on the car's screen.

**One-time setup:** open the Reminders app (Mac or iPhone — they sync via
iCloud) → create a list named **`Peanut`**.

## 2.3 Extend the shortcut (after Action 5, `Speak Text`)

Add these actions in order (these actions exist on both Mac and iPhone —
search for each one):

### Action 7 — `Get List Items`
- **From:** the `Send HTTP Request` result
- **Key:** `links`
- *(If the response has no `links`, this is an empty list — that's fine.)*

### Action 8 — `Get Dictionary Value`
- **Key:** `media` (from the HTTP result). May be `null`.

### Action 9 — `If Any`
- Condition 1: `links` list **is not empty**
- Condition 2: `media` **is not** `null`

### Action 10 — (inside If) `Combine Text`
- Combine: the `links` list **and** the `media` value
- **Separator:** newline
- *(Shortcuts joins list items automatically; the result is one text block of
  URLs.)*

### Action 11 — (inside If) `Add to Reminders`
- **List:** `Peanut`
- **Name:** `Peanut: ` + the `Ask for Input` variable (so you know what each
  reminder was for)
- **Notes:** the `Combine Text` output (the URLs)

### Action 12 — (inside If) `Show Result`
- Text: `Saved to Reminders (Peanut list):` + the combined URLs
- On the phone you can tap these links right away.

### Action 13 (optional) — `If` → `media` is not `null` → `Show Web Page`
- URL: the `media` value
- Shows the generated image immediately on the phone.

**Result:** every answer with links automatically files them in the
**Peanut** Reminders list, named after your question.

## 2.4 CarPlay flow (driving)

1. **"Hey Siri, open Reminders"** → the **Peanut** list → tap a link →
   opens in Safari on the car display.
2. **"Hey Siri, what's in my Peanut list?"** — Siri reads your recent
   reminders hands-free (works with the reminder names + notes).
3. Image links open full-size in the car's Safari.
4. Housekeeping: swipe old Peanut reminders away whenever (they're just an
   inbox, not a permanent archive).

## 2.5 KB mode: async intents with job polling

The family KB lives in the `siri-chat` intent (plus research/demo intents).
Those are **async**: the POST returns `job_id` + "I've started processing…".
To get the real answer in the shortcut, add a **second shortcut**
(name it **`Peanut Brain`** — trigger "Hey Siri, Peanut Brain"):

1. `Ask for Input` (Mac) / `Ask for Text` (iPhone) — prompt: *What do you want Peanut to dig into?*
2. `Text` — body: `{"text": "[Ask for Input]", "intent": "siri-chat"}`
3. `Send HTTP Request` — same URL/headers as the MVP; body = that Text
4. `Get Dictionary Value` — key `job_id`
5. `Repeat` (up to 12 times — i.e. ~60 s; raise for deep research):
   - `Wait` 5 seconds
   - `Send HTTP Request` — **GET** `https://siri.choukalos.com/siri/skills/jobs/` + the `job_id` variable (same `X-API-Key` header)
   - `Get Dictionary Value` — key `status`
   - `If` status **is** `completed` **or** `failed` → `Break`
6. `Get Dictionary Value` — key `summary` (from the last job poll)
7. `Speak Text` — the summary
8. *(Optional)* `Show Result` — summary

> **Tip:** for `deep-research`/demos (minutes long), don't poll from the
> shortcut — let it run and check the **Peanut** Reminders list or the
> presentations portal later (`https://siri.choukalos.com/siri/presentations`).

## 2.6 Optional: a "Peanut inbox" web page

A future nicety: a public read-only page on the homelab listing recent
Peanut outputs (images, links, demos) — browseable from any device including
the car. The Reminders inbox covers today's need; this is a nice-to-have.

---

# Part 3 — Adding Family Members (wife, daughter, …)

**Per person:** one LiteLLM key + one line in `.env` + Caddy + runner +
memory map + their own shortcut. ~15 min per person on the homelab, ~10 min
on their iPhone.

> All commands run on the homelab (thor), `cd /home/chuck/homelab`.
> Replace `<name>` with a lowercase name, e.g. `emily`, `maya`.

## 3.1 Homelab setup (5 steps)

**Step 1 — Create the key** (no budget — local models; spend is still
tracked per key for the family ROI sheet):

```bash
./homelab.sh key add <name> --alias <name>-v1
# for a kid, add a rate cap:  --rpm 10
```
📋 **Copy the `sk-…` key value now** (shown once).

**Step 2 — `.env`** (add the key var, and the memory mapping):

```bash
# in /home/chuck/homelab/.env
LITELLM_KEY_<NAME>=sk-…          # e.g. LITELLM_KEY_EMILY=sk-…
```
and append to the existing `MEMORY_USER_KEYS` line (comma-separated):

```
MEMORY_USER_KEYS=chuck=LITELLM_KEY_CHUCK,dylan=LITELLM_KEY_DYLAN,<name>=LITELLM_KEY_<NAME>
```
This gives the person **their own memory identity** (their "remember …"
facts stay theirs).

**Step 3 — Caddy allowlist** (`caddy/Caddyfile`, the `@siri` handler):
add one more clause to the `@noAuth` expression:

```
&& {http.request.header.X-Api-Key} != '{$LITELLM_KEY_<NAME>}'
```

**Step 4 — skill-runner** (`compose/compose.skill-runner.yml`):
append the key to `SKILL_RUNNER_API_KEY`:

```yaml
SKILL_RUNNER_API_KEY=${LITELLM_KEY_CHUCK},${LITELLM_KEY_DYLAN},${LITELLM_KEY_<NAME>}
```

**Step 5 — Apply + verify:**

```bash
docker compose -f compose/compose.core.yml up -d caddy
docker compose -f compose/compose.skill-runner.yml up -d
# verify (should NOT be a 401):
curl -s -X POST https://siri.choukalos.com/siri/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk-…" \
  -d '{"text":"hello"}'
```

## 3.2 Their iPhone (10 min)

1. Send them the key (securely — Messages from the Mac, not a group chat).
2. Follow **Part 1** with *their* key — build on your Mac (it syncs to their
   iPhone if you share the shortcut) or on their iPhone directly.
3. Done — "Hey Siri, Peanut" works for them, with *their* memory.

## 3.3 Safety notes (kids)

- **Rate cap:** create the key with `--rpm 10` (Step 1) so a runaway
  shortcut loop can't hammer the box.
- **Budgets:** intentionally none (local models) — but per-key spend is
  visible in `./homelab.sh key list` if you ever want to cap someone.
- **Content filtering (optional):** LiteLLM supports guardrails
  (`litellm/config.yml` → `guardrails:`) — e.g. a content-safety model in the
  path. Not configured today; add it if you want a guardrail for the kids.
- **Key hygiene:** `./homelab.sh key delete <name>` to revoke; the key
  value is only shown at creation — if it's lost, create a new one.

## 3.4 Key management cheat sheet

```bash
./homelab.sh key list                    # who has keys + spend
./homelab.sh key info <user>             # alias, models, limits
./homelab.sh key update <user> --rpm N   # change rate limit
./homelab.sh key block <user>            # pause a key
./homelab.sh key delete <user>           # revoke
```

---

# Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| **Can't find an action** in the Mac app | Use the **search field** at the top of the action library. The Mac calls the input action **`Ask for Input`** (iPhone: "Ask for Text"). **`Send HTTP Request` doesn't exist on macOS at all** — build on iPhone, or use the `Run Shell Script` + `curl` variant (§1.4) |
| Shortcut shows **401** | Key wrong, or not in the Caddy allowlist (Part 3, Step 3) |
| Shortcut shows **403 "Invalid API key"** | Key passes Caddy but missing from `SKILL_RUNNER_API_KEY` (Part 3, Step 4) |
| Siri says *"couldn't complete the request"* | Timeout — long intents are async; use the Part 2.5 polling shortcut or check the job later |
| Peanut answers but **no memory** of your facts | Your key isn't in `MEMORY_USER_KEYS` (Part 3, Step 2) — restart skill-runner after editing |
| **Image never shows** | GPU media pipeline down on matrix — check `docker logs skill-runner` for `mcp_media` errors |
| **Job stuck `running`** | `docker logs skill-runner \| tail -50`; check `mcp_knowledge` / `mcp_media` containers are up |
| Siri **mis-triggers** "Peanut" | Rename the shortcut to `Ask Peanut` |
| Links don't open in CarPlay | Make sure the Reminders app is in your CarPlay apps; links open in Safari |

---

# Appendix — Request/Response Reference (abridged)

**POST `https://siri.choukalos.com/siri/api/chat`** · header `X-API-Key: sk-…`

```json
{ "text": "your question", "intent": "siri-chat", "model": null,
  "memory": { "enabled": true } }
```

```json
{
  "speak": "Short spoken answer",
  "display": "Full answer",
  "job_id": "abc123 or null",
  "links": ["https://siri.choukalos.com/..."],
  "media": "https://siri.choukalos.com/media/files/... or null",
  "data": { "model_alias": "matrix-coder", "intent": "siri-chat" }
}
```

**Job poll:** `GET /siri/skills/jobs/{job_id}` (same `X-API-Key`) →
`{status: pending|running|completed|failed|…, summary, error}`

**Health:** `GET /siri/health` (no auth) · **Media:** `GET /siri/media/files/{path}` (public)

Full reference: [README_SIRI.md](./README_SIRI.md).