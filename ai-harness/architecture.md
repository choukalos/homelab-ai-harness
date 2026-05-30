# AI Harness Refactor Plan

## Goal

Consolidate all custom AI tooling into a single extensible `ai-harness` application.

The harness becomes the unified API/tool layer for:

- OpenWebUI
- Siri Shortcuts / CarPlay
- Knowledge base ingestion + search
- Web search + research briefs
- Future AI tooling

Infrastructure services remain separate containers.

---

# Architecture

```text
OpenWebUI / Siri / Apps
          |
          v
+-------------------+
|    ai-harness     |
|-------------------|
| OpenAPI endpoints |
| KB ingestion      |
| KB semantic search|
| Web search        |
| Research briefs   |
| Siri endpoints    |
+-------------------+
      |
      +--> Qdrant
      +--> SearXNG
      +--> Crawl4AI
      +--> LiteLLM
      +--> ai-kb markdown repo

---

# Adding New Harness Features

Each new capability should be added as a first-class feature module.

## Standard module shape

```text
feature_name/
  __init__.py
  router.py      # FastAPI endpoints
  schemas.py     # Pydantic request/response models
  service.py     # Core business logic
  prompts.py     # LLM prompts, if needed
