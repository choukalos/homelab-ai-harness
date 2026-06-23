# Running Tests

## Master orchestrator (runs all smoke tests)

```bash
./tests/harness-smoke-test.sh
```

## Individual smoke tests

```bash
./tests/smoke/test_infra.sh      # workflows, tasks, scheduler
./tests/smoke/test_research.sh   # web search, deep research, brief
./tests/smoke/test_knowledge.sh  # family KB ingest, search, ask
./tests/smoke/test_creative.sh   # charts + presentations
./tests/smoke/test_media.sh      # image gen, clips
./tests/smoke/test_apps.sh       # PM demo + demo workflow
./tests/smoke/test_filetools.sh  # (stub for now)
```

## Channel tests

```bash
./tests/channels/test_siri.sh
./tests/channels/test_openwebui.sh
```

Or via the orchestrator:

```bash
RUN_CHANNEL_TESTS=1 ./tests/harness-smoke-test.sh
```

## Media tests (slower — image/video generation)

```bash
RUN_MEDIA_TESTS=1 ./tests/harness-smoke-test.sh
```

## Legacy scripts (deprecated)

The following files are kept for backward compatibility and delegate to the new location:

| Legacy file | Canonical location |
|---|---|
| `test_deep_research.sh` | `tests/smoke/test_research.sh` |
| `test_charts.sh` | `tests/smoke/test_creative.sh` |
| `test_presentation.sh` | `tests/smoke/test_creative.sh` |
| `test_demo_workflow.sh` | `tests/smoke/test_apps.sh` |
| `workflow-smoke-test.sh` | `tests/smoke/test_infra.sh` |
| `siri-smoke-test.sh` | `tests/channels/test_siri.sh` |

## Cleanup

```bash
./tests/cleanup_presentations.sh           # delete all test presentations
./tests/cleanup_presentations.sh "Smoke"   # delete only matching titles
./tests/cleanup_presentations.sh --dry-run # preview what would be deleted
```
