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

# Hugo extended (pinned) for the Homelab Blog project: tasks build the Hugo
# site and run ./deploy.sh (pushes built output to the deploy branch; the
# portal git-sync publishes choukalos.com). The site requires >= 0.168.0
# extended (homelab-blog README). The tarball extracts the binary directly.
ARG HUGO_VERSION=0.170.1
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) hugoarch=amd64 ;; \
      arm64) hugoarch=arm64 ;; \
      *) echo "unsupported architecture for Hugo: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_${HUGO_VERSION}_checksums.txt" -o /tmp/hugo-checksums.txt; \
    curl -fsSL "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-${hugoarch}.tar.gz" -o /tmp/hugo.tgz; \
    expected=$(grep " hugo_extended_${HUGO_VERSION}_linux-${hugoarch}.tar.gz$" /tmp/hugo-checksums.txt | awk '{print $1}'); \
    actual=$(sha256sum /tmp/hugo.tgz | awk '{print $1}'); \
    [ -n "$expected" ] && [ "$expected" = "$actual" ] || { echo "Hugo tarball checksum mismatch (expected ${expected:-<none>}, got $actual)" >&2; exit 1; }; \
    tar -C /usr/local/bin -xzf /tmp/hugo.tgz; \
    rm -f /tmp/hugo.tgz /tmp/hugo-checksums.txt

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
