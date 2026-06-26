# Tests Directory — Refactoring Plan

> Last updated: 2026-06-24

## Constraints

- **Python is only available inside the ai-harness container**. We develop
  and run tests on the host machine. All test tooling must be shell scripts.
- **test.jpg is a legitimate asset** — used by `smoke/test_media.sh` for
  image editing tests. Do not delete.
- **Cleanup is a separate concern from test execution** — never coupled.
- Tests should be runnable: all at once, or by module/function group.

## Problems

### 1. No tests for `_absolute_url()` URL rewriting

We just added `harness_display_url` and rewrote `_absolute_url()` across
all 7 tool files. The harness returns `http://thor.local:8090/...` which gets
rewritten to `http://192.168.4.54:8090/...` by the tool. **Nothing verifies
this rewrite actually works end-to-end.**

Since we can't run Python on the host, the approach is: hit the harness API
with curl and verify the JSON response contains browser-accessible URLs.

### 2. `channels/test_openwebui.sh` doesn't test demo creation

It covers `list_demos` and `find_demo` (GET only) but never calls the POST
endpoints that create demos. If `_absolute_url()` has a bug, the channel
test won't catch it.

### 3. `smoke/test_apps.sh` labels say "PM Demo" not "Quick Demo" / "Workflow Demo"

The tool was renamed in `apps_tools.py` but the smoke test label wasn't
updated to match. Cosmetic, but creates confusion.

### 4. No test verifies URL rewriting in creative/media responses

`smoke/test_creative.sh` and `smoke/test_media.sh` only check HTTP status
codes (200). They don't verify that `download_url`, `pdf_url`, `image_url`
fields contain LAN-accessible URLs instead of `thor.local`.

### 5. No test for `harness_display_url` valve override

We can't unit-test the valve on the host (no Python). But we can add a
smoke test that: calls an endpoint with a known response, captures the URL,
and verifies it uses the display URL pattern.

### 6. No cleanup for demo artifacts

`smoke/test_apps.sh` creates 3 demo files/directories per run.
Nothing cleans them from `/data/media/demos/`. `cleanup_presentations.sh`
exists but has no demo equivalent.

### 7. `cleanup_presentations.sh` uses `BASE_URL` not `BASE_LOCAL`

After recent `.env` changes, `BASE_URL` may be set to the investor DB URL.
Should use `BASE_LOCAL` for consistency with all other tests.

### 8. No helper to run tests by category

`harness-smoke-test.sh` is the orchestrator but it's all-or-nothing. No way
to run "just the apps tests" or "just the channel tests" without editing
env vars or the script itself.

### 9. README.md has no architecture explanation or "how to add a new test" guide

The current README is a usage quick-reference with zero conceptual scaffolding.
Contributors (especially AI agents) won't know: why tests are all shell, how
the directory structure maps to the harness, what the URL rewrite layer is,
or how to add tests for a new module.

---

## Proposed Plan

### Phase 1 — New helper: `run-tests.sh` (selective test runner)

A lightweight wrapper that lets you run all tests or pick specific groups.

```bash
# Run everything (default set — excludes slow media tests)
bash tests/run-tests.sh

# Run only apps tests
bash tests/run-tests.sh apps

# Run only channel tests
bash tests/run-tests.sh channels

# Run specific modules (comma-separated)
bash tests/run-tests.sh apps,creative,media

# Run all + media (normally skipped — slow image/video gen)
bash tests/run-tests.sh --all

# Just list available test groups
bash tests/run-tests.sh --list
```

Available groups: `infra`, `research`, `knowledge`, `creative`, `media`,
`apps`, `filetools`, `url_rewriting`, `channels`.

This replaces the manual env var dance in `harness-smoke-test.sh` and makes
it easy to test just what you're working on.

### Phase 2 — New smoke test: `smoke/test_url_rewriting.sh`

Shell script that verifies `_absolute_url()` behavior end-to-end by:

1. Calling `/pm/demo` (quick demo — fast response)
2. Parsing the JSON response with `jq`
3. Verifying the `url` field uses `http://192.168.4.54:8090/...` not `http://thor.local:8090/...`
4. Calling `/demos/run` and verifying `local_url` / `public_url` are browser-accessible
5. Calling a creative endpoint (e.g. `/layout/build`) and verifying `html_url` / `pdf_url` use display URL
6. Calling a media endpoint and verifying `url` fields use display URL

This is the **highest-value new test** — it validates the URL rewriting fix
across multiple tool types in one shot.

### Phase 3 — Update existing tests

#### 3.1 `smoke/test_apps.sh` — Update labels

- "PM Demo Generation" → "Quick Demo (PM Demo)"
- "Demo Workflow (sync)" → "Workflow Demo (sync)"
- "Demo Workflow (async)" → "Workflow Demo (async)"

#### 3.2 `channels/test_openwebui.sh` — Add demo creation + URL verification

Add the demo creation POST calls:
```bash
call_post "Quick Demo (apps_tools: create_quick_demo)" "/pm/demo" '...' 300
call_post "Workflow Demo (apps_tools: create_workflow_demo)" "/demos/run" '...' 600
```

Add a `call_post_and_verify_url()` helper that:
1. Makes the call
2. Extracts `url`, `local_url`, `public_url`, `download_url`, `pdf_url`, `html_url` from JSON
3. Asserts none contain `thor.local`

Apply this helper to creative and media tests too.

#### 3.3 `smoke/test_creative.sh` — Add URL verification

After each endpoint call, verify URL fields don't contain `thor.local`.

#### 3.4 `smoke/test_media.sh` — Add URL verification

After image/clip generation, verify `url` fields use LAN IP.

### Phase 4 — Cleanup infrastructure

#### 4.1 `cleanup_demos.sh` (NEW)

Sister to `cleanup_presentations.sh`. Removes demo test artifacts:

```bash
# Usage:
#   bash tests/cleanup_demos.sh               # delete all test demos
#   bash tests/cleanup_demos.sh "Smoke"       # delete only matching titles
#   bash tests/cleanup_demos.sh --dry-run     # preview what would be deleted
```

Handles:
- Flat `.html` files in `/data/media/demos/`
- Workflow demo subdirectories with `metadata.json`
- Title patterns: "Smoke Test", "OpenWebUI", "Siri Demo"

#### 4.2 `cleanup_presentations.sh` — Fix BASE_URL → BASE_LOCAL

One-line fix.

#### 4.3 `run-cleanup.sh` (NEW)

Simple helper to run all cleanup:

```bash
bash tests/run-cleanup.sh        # runs both demo + presentation cleanup
bash tests/run-cleanup.sh --dry-run
bash tests/run-cleanup.sh demos      # just demos
bash tests/run-cleanup.sh presentations  # just presentations
```

### Phase 5 — Housekeeping

#### 5.1 Update `harness-smoke-test.sh`

- Update "Apps" label to mention quick_demo + workflow_demo
- Keep it as the default "run all" for backward compat
- Add a comment pointing to `run-tests.sh` for granular control

#### 5.2 `cleanup_all.sh` (NEW)

Combination script: `run-cleanup.sh` + optionally reset any persistent state.
Convenient pre-test cleanup: `bash tests/cleanup_all.sh && bash tests/run-tests.sh`

---

## Phase 6 — New README.md (full draft below)

Replace `tests/README.md` with this. Designed to be both human-readable
and AI-agent-parsable: clear structure, explicit conventions, no ambiguity.

```markdown
# AI Harness — Tests

## How it works

All tests are **shell scripts** (bash + curl + jq). Python is only available
inside the ai-harness container, so we develop and run tests on the host.

**Smoke tests** hit the live harness API and verify HTTP status codes + response
structure. They require the ai-harness container to be running.

**Cleanup scripts** remove test artifacts from the harness filesystem. They are
a **separate action** — never baked into test execution. Run cleanup before or
after testing as needed.

### Directory layout

```
tests/
├── run-tests.sh           # Selective test runner (pick groups, or run all)
├── run-cleanup.sh         # Selective cleanup runner
├── cleanup_all.sh         # Combined pre-test cleanup
├── harness-smoke-test.sh  # Legacy master orchestrator (still works)
├── smoke/                 # Module smoke tests
│   ├── test_infra.sh              # Workflows, tasks, scheduler
│   ├── test_research.sh           # Web search, deep research, research brief
│   ├── test_knowledge.sh          # Family KB: ingest, search, ask
│   ├── test_creative.sh           # Charts + presentations
│   ├── test_media.sh              # Image gen, image edit, clips
│   ├── test_apps.sh               # Quick demo + workflow demo
│   ├── test_filetools.sh          # (stub — no endpoints yet)
│   └── test_url_rewriting.sh      # Cross-module URL rewrite verification
├── channels/              # Channel integration tests
│   ├── test_siri.sh                 # Siri voice channel (local + public)
│   └── test_openwebui.sh            # Open WebUI tool endpoints
├── cleanup_presentations.sh # Delete test presentation artifacts
├── cleanup_demos.sh         # Delete test demo artifacts
└── test.jpg                 # Image edit test asset (DO NOT DELETE)
```

### URL rewriting layer

The harness internally serves media at `http://thor.local:8090/...` but the
Open WebUI tools rewrite this to a browser-accessible LAN URL
(e.g. `http://192.168.4.54:8090/...`) via the `harness_display_url` valve.

`smoke/test_url_rewriting.sh` validates this rewrite across all tool types
(demo, creative, media) to ensure users get working links.

## Running tests

```bash
# Run all tests (default set — excludes slow media tests)
bash tests/run-tests.sh

# Run specific group(s)
bash tests/run-tests.sh apps
bash tests/run-tests.sh apps,creative
bash tests/run-tests.sh channels

# Run everything including slow media tests
bash tests/run-tests.sh --all

# List available groups
bash tests/run-tests.sh --list

# Legacy: run all via orchestrator (still works)
bash tests/harness-smoke-test.sh
```

## Cleaning up

```bash
# Clean all test artifacts (demos + presentations)
bash tests/run-cleanup.sh

# Preview without deleting
bash tests/run-cleanup.sh --dry-run

# Clean only one type
bash tests/run-cleanup.sh demos
bash tests/run-cleanup.sh presentations
```

## Adding a new test

1. Create `smoke/test_your_module.sh` in the `smoke/` directory
2. Follow the existing pattern: source `.env`, define `BASE_URL` + `API_KEY`,
   write `call_post()` / `call_get()` helpers, add test calls
3. Register it in `run-tests.sh` under the appropriate group
4. If your module returns URLs, verify they don't contain `thor.local`

For channel-specific tests, add to `channels/test_your_channel.sh` and
register in `run-tests.sh` under the `channels` group.

## Deprecated shim scripts

The following root-level scripts are kept for backward compatibility and
delegate to the canonical location:

| Legacy file | Canonical location |
|---|---|
| `test_deep_research.sh` | `tests/smoke/test_research.sh` |
| `test_charts.sh` | `tests/smoke/test_creative.sh` |
| `test_presentation.sh` | `tests/smoke/test_creative.sh` |
| `test_demo_workflow.sh` | `tests/smoke/test_apps.sh` |
| `workflow-smoke-test.sh` | `tests/smoke/test_infra.sh` |
| `siri-smoke-test.sh` | `tests/channels/test_siri.sh` |
```

---

## File Map After Refactoring

```
tests/
├── README.md                          # REWRITTEN (see Phase 6 draft)
├── plan.md                            # This file
├── run-tests.sh                       # NEW — selective test runner
├── run-cleanup.sh                     # NEW — selective cleanup runner
├── cleanup_all.sh                     # NEW — combined pre-test cleanup
├── harness-smoke-test.sh              # Updated (labels + comment)
├── cleanup_presentations.sh           # Fixed (BASE_URL → BASE_LOCAL)
├── cleanup_demos.sh                   # NEW — demo artifact cleanup
├── smoke/
│   ├── test_infra.sh                  # Unchanged
│   ├── test_research.sh               # Unchanged
│   ├── test_knowledge.sh              # Unchanged
│   ├── test_creative.sh               # Updated (URL verification)
│   ├── test_media.sh                  # Updated (URL verification)
│   ├── test_apps.sh                   # Updated (labels)
│   ├── test_filetools.sh              # Unchanged (stub)
│   └── test_url_rewriting.sh          # NEW — cross-module URL test
├── channels/
│   ├── test_siri.sh                   # Unchanged
│   └── test_openwebui.sh              # Updated (demo POSTs + URL check)
├── test_deep_research.sh              # DEPRECATED shim — keep
├── test_charts.sh                     # DEPRECATED shim — keep
├── test_presentation.sh               # DEPRECATED shim — keep
├── test_demo_workflow.sh              # DEPRECATED shim — keep
├── workflow-smoke-test.sh             # DEPRECATED shim — keep
├── siri-smoke-test.sh                 # DEPRECATED shim — keep
└── test.jpg                           # KEEP — media image edit test asset
```

## Priority

| Priority | Task | Value |
|---|---|---|
| **1** | `smoke/test_url_rewriting.sh` | Highest — validates the URL fix end-to-end |
| **2** | `run-tests.sh` | High — makes testing workflow actually usable |
| **3** | `cleanup_demos.sh` + `run-cleanup.sh` | Medium — prevents artifact pile-up |
| **4** | Update `channels/test_openwebui.sh` | Medium — covers demo creation in channel tests |
| **5** | URL verification in creative/media tests | Medium — catches future regressions |
| **6** | Label updates in `test_apps.sh` | Low — cosmetic alignment |
| **7** | `cleanup_presentations.sh` fix | Low — one-line fix |
| **8** | New `README.md` | High — docs for humans + AI agents |
| **9** | `harness-smoke-test.sh` + `cleanup_all.sh` | Low — housekeeping |

## Implementation Notes

- **All shell, no Python** — `jq` is the JSON parser (check it's available on
  host; if not, fall back to `python3 -c` only inside the container).
- `run-tests.sh` should source `.env` once at the top and pass vars to sub-scripts.
- `run-tests.sh` should accept `--all` to include normally-skipped tests (media).
- The URL rewriting test (`test_url_rewriting.sh`) is a **smoke test**, not a
  unit test — it needs the harness running. That's fine and consistent with
  our approach.
- `cleanup_demos.sh` should be idempotent — safe to run even if no test demos exist.
- The new README is in Phase 6 above — paste it directly into `tests/README.md`.
