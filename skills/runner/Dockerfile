# Thor Skill Runner — container mode
# Runs on port 8091 on ai-net, calls LiteLLM for LLM + MCP

FROM python:3.12-slim

WORKDIR /app

# Copy application code
COPY main.py .
COPY scheduler.py .
COPY sessions.py .
COPY proposals.py .
COPY jobs_metrics.py .
COPY learning_metrics.py .
COPY pyproject.toml .
COPY memory/ ./memory/

# Install runtime dependencies directly (single-file app, no package distribution needed)
# mem0ai pinned to the version verified in Phase 1 (round-trip + restore).
# fastembed (the mem0ai[extras] requirement): enables mem0's hybrid BM25
# keyword + dense-vector search in the Qdrant store. Added 2026-11-14 after the
# Phase 13 eval (memory_todo.md) found retrieval was dense-only (mem0 logs
# "fastembed not installed - BM25 keyword search disabled"). The Qdrant/bm25
# model (~128 KB) is pre-baked below so runtime searches never need HF Hub.
# git: the harness_reflection skill (Phase 3) reads the homelab repo's git
# log (read-only mount) as one of its five inputs.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "pydantic>=2.0.0" \
    "httpx>=0.27.0" \
    "pyyaml>=6.0" \
    "pymysql>=1.1.0" \
    "mem0ai==2.0.19" \
    "fastembed==0.9.1"

# fastembed model cache: explicit path so a future fastembed default change
# can't orphan the pre-baked model (see next step).
ENV FASTEMBED_CACHE_PATH=/tmp/fastembed_cache

# Pre-download the Qdrant/bm25 sparse-encoder model into the image (~128 KB)
# so the first search after any rebuild is offline-deterministic. If the
# encoder ever fails to load at runtime, mem0 degrades gracefully to
# dense-only (try/except in mem0.vector_stores.qdrant).
# chown: the build runs as root but the container runs as user 1000 (chuck);
# without this, huggingface_hub's tree-cache update fails with
# "Permission denied" (harmless but noisy on every start).
RUN python -c "from fastembed import SparseTextEmbedding; list(SparseTextEmbedding(model_name='Qdrant/bm25').embed(['warmup']))" \
    && chown -R 1000:1000 /tmp/fastembed_cache

# Runtime config
ENV SKILL_RUNNER_PORT=8091
ENV SKILL_RUNNER_HOST=0.0.0.0
ENV LITELLM_BASE_URL=http://litellm-proxy:4000
ENV PYTHONUNBUFFERED=1

# MCP server URL defaults
ENV MCP_SERVER_SEARCH_URL=http://mcp_search:8000
ENV MCP_SERVER_KNOWLEDGE_URL=http://mcp_knowledge:8000
ENV MCP_SERVER_CRAWL_URL=http://mcp_crawl:8000
ENV MCP_SERVER_FILESYSTEM_READONLY_URL=http://mcp_filesystem_readonly:8000

EXPOSE 8091

# Create required application directories
RUN mkdir -p /app/skills /app/logs

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8091", "--log-level", "info"]
