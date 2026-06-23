# AI Harness Reorg — Implementation Plan

## Current State

```
ai-harness/
├── app.py
├── core/                # config, llm, celery, cache, security
├── tasks/               # celery task queue
├── scheduler/           # celery beat + redbeat
├── workflows/           # workflow engine
├── web_search/
├── deep_research/
├── market_research/
├── family_kb/
├── presentation/
├── charts/
├── layout/
├── media/
├── pm_demo/
├── demo_workflow/
├── filetools/
├── siri/
├── openwebui_tools/
│   ├── harness_tools.py          (~900 lines, monolithic)
│   └── presentation_tools.py     (~500 lines)
├── tests/
│   ├── harness-smoke-test.sh
│   ├── siri-smoke-test.sh
│   ├── test_charts.sh
│   ├── test_deep_research.sh
│   ├── test_demo_workflow.sh
│   ├── test_presentation.sh
│   ├── workflow-smoke-test.sh
│   └── cleanup_presentations.sh
├── requirements.txt
└── Dockerfile
```

## Target State

```
ai-harness/
├── app.py
├── STRATEGY.md
├── plan.md
├── infra/
│   ├── core/              # config, llm, celery_app, cache, security
│   ├── tasks/             # celery task queue
│   ├── scheduler/         # celery beat + redbeat
│   └── workflows/         # workflow engine
├── research/
│   ├── web_search/
│   ├── deep_research/
│   └── market_research/
├── knowledge/
│   └── family_kb/
├── creative/
│   ├── presentation/
│   ├── charts/
│   └── layout/
├── media/
├── apps/
│   ├── pm_demo/
│   └── demo_workflow/
├── filetools/
├── channels/
│   ├── openwebui/
│   │   ├── harness_base.py
│   │   ├── research_tools.py
│   │   ├── knowledge_tools.py
│   │   ├── creative_tools.py
│   │   ├── media_tools.py
│   │   ├── apps_tools.py
│   │   ├── filetools_tools.py
│   │   └── scheduler_tools.py
│   └── siri/
├── tests/
│   ├── smoke/
│   │   ├── test_research.sh
│   │   ├── test_knowledge.sh
│   │   ├── test_creative.sh
│   │   ├── test_media.sh
│   │   ├── test_apps.sh
│   │   ├── test_filetools.sh
│   │   └── test_infra.sh
│   ├── channels/
│   │   └── test_siri.sh
│   ├── harness-smoke-test.sh    # master (runs all)
│   └── cleanup_presentations.sh
├── requirements.txt
└── Dockerfile
```

---

## Phase 1: Infrastructure Folder (Low Risk)

**Goal:** Move `core/`, `tasks/`, `scheduler/`, `workflows/` under `infra/`.

### Steps

1. **Create the infra folder and move modules:**

   ```bash
   mkdir -p infra
   mv core infra/
   mv tasks infra/
   mv scheduler infra/
   mv workflows infra/
   ```

2. **Add `infra/__init__.py`:**

   ```python
   # Makes infra a proper Python package
   ```

3. **Update all imports across the entire codebase:**

   Search-and-replace patterns (run across all `.py` files in `ai-harness/`):

   | Old Import | New Import |
   |---|---|
   | `from core.config import` | `from infra.core.config import` |
   | `from core.llm import` | `from infra.core.llm import` |
   | `from core.celery_app import` | `from infra.core.celery_app import` |
   | `from core.cache import` | `from infra.core.cache import` |
   | `from core.security import` | `from infra.core.security import` |
   | `from tasks.router import` | `from infra.tasks.router import` |
   | `from tasks.schemas import` | `from infra.tasks.schemas import` |
   | `from tasks.service import` | `from infra.tasks.service import` |
   | `from tasks.tasks import` | `from infra.tasks.tasks import` |
   | `from scheduler.router import` | `from infra.scheduler.router import` |
   | `from scheduler.schemas import` | `from infra.scheduler.schemas import` |
   | `from scheduler.service import` | `from infra.scheduler.service import` |
   | `from scheduler.store import` | `from infra.scheduler.store import` |
   | `from scheduler.models import` | `from infra.scheduler.models import` |
   | `from scheduler.tasks import` | `from infra.scheduler.tasks import` |
   | `from workflows import` | `from infra.workflows import` |
   | `from workflows.router import` | `from infra.workflows.router import` |
   | `from workflows.schemas import` | `from infra.workflows.schemas import` |
   | `from workflows.service import` | `from infra.workflows.service import` |
   | `from workflows.db import` | `from infra.workflows.db import` |

4. **Update `app.py` imports** to match the new paths.

5. **Update `compose.ai-harness.yml`** — the Celery worker command references `core.celery_app`:

   ```yaml
   # Old:
   command: celery -A core.celery_app.celery worker ...
   # New:
   command: celery -A infra.core.celery_app.celery worker ...
   ```

6. **Verify:**
   - `python -c "from infra.core.config import *"` — no import errors
   - `docker compose -f compose.ai-harness.yml build` — builds clean
   - Run `harness-smoke-test.sh` — all green

### Risk: Medium (lots of import changes, but mechanical and reversible)
### Estimated effort: 1–2 hours

---

## Phase 2: Feature Group Folders

**Goal:** Group related modules under domain folders (`research/`, `knowledge/`, `creative/`, `apps/`).

### Steps

1. **Create group folders and move modules:**

   ```bash
   mkdir -p research
   mv web_search research/
   mv deep_research research/
   mv market_research research/

   mkdir -p knowledge
   mv family_kb knowledge/

   mkdir -p creative
   mv presentation creative/
   mv charts creative/
   mv layout creative/

   mkdir -p apps
   mv pm_demo apps/
   mv demo_workflow apps/
   ```

2. **Add `__init__.py` to each group folder** to make them Python packages.

3. **Update all cross-module imports.** This is the key question: do we use the fully-qualified path or keep short names?

   **Recommendation:** Keep short internal names within the module, use fully-qualified for cross-group references.

   Examples of imports that need updating:

   | Old | New |
   |---|---|
   | `from web_search.router import` | `from research.web_search.router import` |
   | `from deep_research.router import` | `from research.deep_research.router import` |
   | `from market_research.router import` | `from research.market_research.router import` |
   | `from market_research.tasks import` | `from research.market_research.tasks import` |
   | `from family_kb.router import` | `from knowledge.family_kb.router import` |
   | `from presentation.router import` | `from creative.presentation.router import` |
   | `from presentation.tasks import` | `from creative.presentation.tasks import` |
   | `from charts.router import` | `from creative.charts.router import` |
   | `from layout.router import` | `from creative.layout.router import` |
   | `from pm_demo.router import` | `from apps.pm_demo.router import` |
   | `from demo_workflow.router import` | `from apps.demo_workflow.router import` |

   **Internal imports** (e.g., within `deep_research/service.py` importing from `deep_research/prompts.py`) can stay as-relative imports (`from .prompts import ...`) and won't change.

4. **Update `app.py`** with all new router import paths and prefix adjustments:

   ```python
   # Old:
   app.include_router(web_search_router, prefix="/web", tags=["web"])
   # New (prefix stays the same — this is the external API contract):
   app.include_router(web_search_router, prefix="/web", tags=["web"])
   ```

   **Important:** The URL prefixes (`/web`, `/kb`, `/presentation`, etc.) do **NOT** change. The directory reorg is internal only. External API consumers see no difference.

5. **Update `family_kb_watch.py`** imports if it references moved modules.

6. **Verify:**
   - `docker compose -f compose.ai-harness.yml build` — builds clean
   - `harness-smoke-test.sh` — all green
   - Spot-check a few API endpoints manually

### Risk: Medium (import changes, but URL contract is preserved)
### Estimated effort: 1–2 hours

---

## Phase 3: Channels Folder + Siri Migration

**Goal:** Move consumer adapters under `channels/`.

### Steps

1. **Create channels folder:**

   ```bash
   mkdir -p channels/openwebui
   mkdir -p channels/siri
   ```

2. **Move Siri module:**

   ```bash
   mv siri channels/
   ```

3. **Update Siri imports in `app.py`:**

   ```python
   # Old:
   from siri.router import router as siri_router
   # New:
   from channels.siri.router import router as siri_router
   ```

4. **Move openwebui_tools:**

   ```bash
   mv openwebui_tools/* channels/openwebui/
   rmdir openwebui_tools
   ```

   Note: These files are **standalone Python scripts** — they don't import from the harness codebase (they call it over HTTP). So no import changes needed inside them.

5. **Update `tests/siri-smoke-test.sh`** if it references the old path.

6. **Verify:**
   - `docker compose -f compose.ai-harness.yml build` — builds clean
   - `siri-smoke-test.sh` — all green

### Risk: Low (siri is self-contained, openwebui_tools are standalone)
### Estimated effort: 30 min

---

## Phase 4: Split OpenWebUI Tool Files

**Goal:** Replace the two monolithic tool files with per-group modular files sharing a common base.

### Steps

1. **Create `channels/openwebui/harness_base.py`:**

   Extract the shared boilerplate from the current `harness_tools.py`:
   - `Valves` class (harness_url, harness_api_key)
   - `__init__()`
   - `_headers()`
   - `_absolute_url()`
   - `_post()`
   - `_get()` (if not already present)

2. **Analyze `harness_tools.py` (~900 lines) and map each tool method to its group:**

   | Method | Target File |
   |---|---|
   | `web_search()` | `research_tools.py` |
   | `summarize_web_search()` | `research_tools.py` |
   | `research_brief_web_search()` | `research_tools.py` |
   | `deep_research_*()` | `research_tools.py` |
   | `market_research_*()` | `research_tools.py` |
   | `search_kb()`, `search_kb_semantic()`, etc. | `knowledge_tools.py` |
   | `generate_image()`, `edit_image()`, `generate_video()` | `media_tools.py` |
   | `create_presentation()`, `generate_outline()`, etc. | `creative_tools.py` |
   | `create_chart()`, etc. | `creative_tools.py` |
   | `create_layout()` | `creative_tools.py` |
   | `create_demo()`, `list_demos()`, `find_demo()` | `apps_tools.py` |
   | `read_file()`, `write_file()`, etc. | `filetools_tools.py` |

3. **Create each new tool file** with the OpenWebUI `class Tools` pattern, importing/copying the base class helper methods and declaring only the methods for that group.

4. **Handle `presentation_tools.py`** — its methods go into `creative_tools.py`. The standalone `presentation_tools.py` can be kept as a convenience for users who only want presentations (it imports from the same base).

5. **Create `scheduler_tools.py`** if schedule management should be exposed to OpenWebUI users.

6. **Keep `harness_tools.py` and `presentation_tools.py` as deprecated** with a note pointing to the new files. Remove after a transition period.

7. **Update `channels/openwebui/README.md`** with the new file structure and install instructions.

### Risk: Low (these are standalone files, not part of the harness container)
### Estimated effort: 2–3 hours

---

## Phase 5: Test Reorganization

**Goal:** Mirror the new structure in the test directory.

### Steps

1. **Create test subdirectories:**

   ```bash
   mkdir -p tests/smoke
   mkdir -p tests/channels
   ```

2. **Rename and move existing tests:**

   | Old File | New Location | New Name |
   |---|---|---|
   | `test_deep_research.sh` | `tests/smoke/` | `test_research.sh` (merge web + deep + market) |
   | `test_charts.sh` | `tests/smoke/` | `test_creative.sh` (merge charts + presentation) |
   | `test_presentation.sh` | merged into above | — |
   | `test_demo_workflow.sh` | `tests/smoke/` | `test_apps.sh` |
   | `harness-smoke-test.sh` stays at top level | — | runs all smoke tests |
   | `workflow-smoke-test.sh` | `tests/smoke/` | `test_infra.sh` |
   | `siri-smoke-test.sh` | `tests/channels/` | `test_siri.sh` |

3. **Merge overlapping tests:**
   - `test_deep_research.sh` + market research tests → `test_research.sh`
   - `test_charts.sh` + `test_presentation.sh` → `test_creative.sh`
   - Keep media/image tests as `test_media.sh` (currently embedded in `harness-smoke-test.sh` via `RUN_MEDIA_TESTS=1`)

4. **Update `harness-smoke-test.sh`** to call the individual smoke tests:

   ```bash
   #!/usr/bin/env bash
   set -e
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   
   echo "=== Running smoke tests ==="
   "$SCRIPT_DIR/smoke/test_infra.sh"
   "$SCRIPT_DIR/smoke/test_research.sh"
   "$SCRIPT_DIR/smoke/test_knowledge.sh"
   "$SCRIPT_DIR/smoke/test_creative.sh"
   "$SCRIPT_DIR/smoke/test_media.sh"
   "$SCRIPT_DIR/smoke/test_apps.sh"
   "$SCRIPT_DIR/smoke/test_filetools.sh"
   "$SCRIPT_DIR/channels/test_siri.sh"
   echo "=== All smoke tests passed ==="
   ```

5. **Update any hardcoded paths** inside test scripts that reference old module paths.

### Risk: Low (tests are shell scripts, not compiled)
### Estimated effort: 1–2 hours

---

## Phase 6: Polish & Verification

**Goal:** Final cleanup and full verification.

### Steps

1. **Update `architecture.md`** or replace its content with a pointer to `STRATEGY.md`.

2. **Update `README.md`** in the harness root to reflect the new structure.

3. **Update `Dockerfile`** if it has any hardcoded paths to old module locations.

4. **Update `compose.ai-harness.yml`** — verify the Celery worker command works with the new `infra.core.celery_app` path (changed in Phase 1).

5. **Update `compose.ai-harness.yml`** — verify the beat command references the correct module path.

6. **Update `.env`** references if any point to old paths.

7. **Full verification run:**

   ```bash
   # Build
   docker compose -f compose.ai-harness.yml build

   # Start
   docker compose -f compose.ai-harness.yml up -d

   # Smoke test
   ./tests/harness-smoke-test.sh

   # API health check
   curl http://thor.local:8090/health

   # Spot-check key endpoints
   curl http://thor.local:8090/web/search -H "Content-Type: application/json" -d '{"query":"test"}'
   curl http://thuck.local:8090/kb/
   curl http://thor.local:8090/presentation/list
   ```

8. **Clean up:**
   - Remove `__pycache__` directories
   - Remove old `harness_tools.py` / `presentation_tools.py` from top-level (already moved)
   - Remove any `.bak` files (e.g., `comfy_client.py.bak`)

### Risk: Low
### Estimated effort: 1 hour

---

## Dependencies Between Phases

```
Phase 1 (infra/) ──► Phase 2 (feature groups) ──► Phase 5 (tests)
                                                                    │
Phase 3 (channels/) ──► Phase 4 (tool split)                       │
                                                                    ▼
                                                               Phase 6 (polish)
```

- Phase 1 and Phase 3 can happen in any order (they touch different code)
- Phase 2 depends on Phase 1 (imports reference `infra.`)
- Phase 4 does NOT depend on the harness reorg (tool files are standalone)
- Phase 5 depends on Phases 1–3 (test paths reference new module locations)
- Phase 6 depends on everything

## Recommended Order

1. **Phase 1** — infra folder (biggest import impact, get it out of the way)
2. **Phase 2** — feature groups (next biggest import impact)
3. **Phase 3** — channels folder (low risk, small change)
4. **Phase 4** — tool file split (standalone, can do in parallel with 1–3)
5. **Phase 5** — test reorg (depends on 1–3)
6. **Phase 6** — polish (depends on all)

**Total estimated effort: 6–10 hours** spread across phases. Each phase is independently buildable and testable.

---

## Rollback Plan

Each phase is a git commit. If something breaks:

```bash
# Rollback to before a phase
git revert <commit-hash>

# Or reset to a known-good state
git reset --hard <commit-before-phase>
```

Since all URL prefixes are preserved, external consumers (OpenWebUI, Siri) see no breaking changes regardless of which phase you're on.
