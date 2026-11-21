# mcp_kanban — single-container build (homelab MCP server).
#
# Toolchain: node (Pi runtime) + python + go — the supported task toolchain,
# documented in README.md (extensible). NO ffmpeg/yt-dlp: media analysis goes
# through the media pipeline's MCP tools exposed by the LiteLLM proxy.
#
# Container behavior: installs the app, runs migrations (versioned +
# idempotent, at app startup via src/db), starts via entrypoint.sh
# (harness skills pull + model validation, then the app).
FROM node:22-bookworm

# python + go for agent workspaces; git for clones/pushes; curl for the
# healthcheck. Lean install (no recommends).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      python3 \
      python3-pip \
      python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Modern Go from the official tarball (distro golang-go is too old for
# current go.mod directives). Architecture-aware (amd64/arm64).
ARG GO_VERSION=1.24.5
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) goarch=amd64 ;; \
      arm64) goarch=arm64 ;; \
      *) echo "unsupported architecture for Go: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${goarch}.tar.gz" -o /tmp/go.tgz; \
    tar -C /usr/local -xzf /tmp/go.tgz; \
    rm /tmp/go.tgz
ENV PATH=$PATH:/usr/local/go/bin

WORKDIR /app

# Dependencies first (layer cache), then build the TypeScript app.
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build \
    && npm prune --omit=dev \
    && npm cache clean --force

# Entrypoint: harness skills clone/pull + model validation, then start.
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# /data = persistent app state; /workspace = agent scratch (host-mounted).
VOLUME ["/data", "/workspace"]

ENV NODE_ENV=production \
    PORT=3000 \
    BIND_ADDR=0.0.0.0 \
    DB_DRIVER=sqlite \
    HARNESS_REPO_URL=https://github.com/choukalos/homelab-ai-harness \
    HARNESS_SKILLS_PATH=agents-skills

EXPOSE 3000

ENTRYPOINT ["/app/entrypoint.sh"]
