# Thor Skill Runner — container mode
# Runs on port 8091 on ai-net, calls LiteLLM for LLM + MCP

FROM python:3.12-slim

WORKDIR /app

# Copy application code
COPY main.py .
COPY scheduler.py .
COPY pyproject.toml .
COPY memory/ ./memory/

# Install runtime dependencies directly (single-file app, no package distribution needed)
# mem0ai pinned to the version verified in Phase 1 (round-trip + restore).
# fastembed intentionally NOT installed: BM25/hybrid keyword search disabled
# (dense-only semantic search is the v1 design; see Phase 1 gotchas).
RUN pip install --no-cache-dir \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "pydantic>=2.0.0" \
    "httpx>=0.27.0" \
    "pyyaml>=6.0" \
    "pymysql>=1.1.0" \
    "mem0ai==2.0.19"

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
