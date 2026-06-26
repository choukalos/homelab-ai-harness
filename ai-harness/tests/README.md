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
├── run-tests.sh              # Selective test runner (pick groups, or run all)
├── run-cleanup.sh            # Selective cleanup runner
├── cleanup_all.sh            # Combined pre-test cleanup
├── harness-smoke-test.sh     # Legacy master orchestrator (still works)
├── smoke/                    # Module smoke tests
│   ├── test_infra.sh              # Workflows, tasks, scheduler
│   ├── test_research.sh           # Web search, deep research, research brief
│   ├── test_knowledge.sh          # Family KB: ingest, search, ask
│   ├── test_creative.sh           # Charts + presentations
│   ├── test_media.sh              # Image gen, image edit, clips
│   ├── test_apps.sh               # Quick demo + workflow demo
│   ├── test_filetools.sh          # (stub — no endpoints yet)
│   └── test_url_rewriting.sh      # Cross-module URL rewrite verification
├── channels/                 # Channel integration tests
│   ├── test_siri.sh                 # Siri voice channel (local + public)
│   └── test_openwebui.sh            # Open WebUI tool endpoints
├── cleanup_presentations.sh  # Delete test presentation artifacts
├── cleanup_demos.sh          # Delete test demo artifacts
└── test.jpg                  # Image edit test asset (DO NOT DELETE)
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

# Combined cleanup + optional state reset
bash tests/cleanup_all.sh
bash tests/cleanup_all.sh --with-state-reset    # + reset workflow checkpoints
bash tests/cleanup_all.sh --dry-run              # preview
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
