#!/usr/bin/env bash
# skill-hub-register.sh — register every agents-skills/<name>/ SKILL.md wrapper
# into the LiteLLM Skill Hub (POST /claude-code/plugins) and enable it.
#
# Why: clients (pi, Claude Code, any MCP client) discover skills through the
# Skill Hub, which is sourced from this repo's agents-skills/ git-subdirs.
# Adding a new skill to agents-skills/ is not enough — it must be registered
# + enabled in LiteLLM_ClaudeCodePluginTable or it won't appear in
# /claude-code/marketplace.json. This script makes that reproducible and
# idempotent: run it after `git pull` to sync the hub with the repo.
#
# The Skill Hub create endpoint requires the LiteLLM MASTER key (per-user
# keys get 403). Run on thor (or anywhere with the key + LAN access):
#
#   cd ~/homelab-ai-harness
#   git pull
#   ./scripts/skill-hub-register.sh            # register + enable all
#   ./scripts/skill-hub-register.sh --list     # show hub state only
#   LITELLM_BASE_URL=http://thor.local:4000 ./scripts/skill-hub-register.sh
#
# Idempotency: skills already registered in the hub are skipped (their
# version/description are NOT rewritten — to force a re-register of one
# skill, delete it first: DELETE /claude-code/plugins/<name>).
#
# Env:
#   LITELLM_MASTER_KEY   master key (required; also read from .env next to
#                        the repo root if not already in the environment)
#   LITELLM_BASE_URL     default http://localhost:4000 (running on thor)
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
if [[ -z "${LITELLM_MASTER_KEY:-}" && -f .env ]]; then
    # shellcheck disable=SC1091
    set -a; source ./.env; set +a
fi
: "${LITELLM_MASTER_KEY:?LITELLM_MASTER_KEY not set (export it or run on thor where .env lives)}"
BASE_URL="${LITELLM_BASE_URL:-http://localhost:4000}"
BASE_URL="${BASE_URL%/}"
# The LiteLLM port is published on THOR_IP (192.168.4.54), not 127.0.0.1 —
# on thor the localhost default is unreachable. Fall back to the LAN IP.
if ! curl -sf --max-time 3 -o /dev/null "${BASE_URL}/health/liveliness" 2>/dev/null; then
    ALT="http://192.168.4.54:4000"
    if [[ "$BASE_URL" != "$ALT" ]] && curl -sf --max-time 3 -o /dev/null "${ALT}/health/liveliness" 2>/dev/null; then
        echo "note: ${BASE_URL} unreachable — using ${ALT}" >&2
        BASE_URL="$ALT"
    fi
fi
REPO_URL="https://github.com/choukalos/homelab-ai-harness.git"
SKILLS_DIR="agents-skills"

AUTH=(-H "Authorization: Bearer ${LITELLM_MASTER_KEY}" -H "Content-Type: application/json")

# ---------------------------------------------------------------------------
# Parse SKILL.md frontmatter (strict YAML, same rule as tests/test_skills_yaml.py)
# ---------------------------------------------------------------------------
parse_frontmatter() { # $1 = SKILL.md path -> prints "name<TAB>description"
    python3 - "$1" <<'PYEOF'
import sys

path = sys.argv[1]
text = open(path).read()
if not text.startswith("---"):
    sys.exit(f"{path}: no frontmatter")
fm_text = text[4:].split("\n---", 1)[0]

try:
    import yaml
    fm = yaml.safe_load(fm_text)
    name, desc = fm.get("name"), (fm.get("description") or "").strip()
except ImportError:
    # Fallback: minimal frontmatter parser (name + description, incl. '>'/'|' blocks).
    # Only used when PyYAML is missing (thor has it — pre-commit hook depends on it).
    name, desc, key, block = None, None, None, []
    for line in fm_text.splitlines():
        if line.startswith("  ") and key == "description" and block is not None:
            block.append(line.strip())
            continue
        if line.startswith("  "):
            continue
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"').strip("'")
            key = None
        elif line.startswith("description:"):
            val = line.split(":", 1)[1].strip()
            if val in (">", "|", ">-", "|-"):
                block = []
                key = "description"
            else:
                desc = val.strip('"').strip("'")
                key = None
    if key == "description" and block is not None:
        desc = " ".join(block)
    name, desc = (name or ""), (desc or "")

if not name or not desc:
    sys.exit(f"{path}: missing name/description in frontmatter")
print(f"{name}\t{desc}")
PYEOF
}

# ---------------------------------------------------------------------------
# Current hub state
# ---------------------------------------------------------------------------
hub_names() {
    curl -sf --max-time 15 "${AUTH[@]}" "${BASE_URL}/claude-code/plugins" \
        | python3 -c "
import json, sys
body = json.load(sys.stdin)
items = body if isinstance(body, list) else body.get('plugins') or body.get('data') or body.get('skills') or []
print('\n'.join(p.get('name', '') for p in items if p.get('name')))
"
}

if [[ "${1:-}" == "--list" ]]; then
    echo "Skill Hub state at ${BASE_URL}:"
    hub_names | sed 's/^/  /'
    exit 0
fi

REGISTERED=$(hub_names)

# ---------------------------------------------------------------------------
# Register + enable every agents-skills/<name>
# ---------------------------------------------------------------------------
added=0; skipped=0; failed=0
for skill_md in "$SKILLS_DIR"/*/SKILL.md; do
    [[ -e "$skill_md" ]] || continue
    IFS=$'\t' read -r name desc < <(parse_frontmatter "$skill_md")
    if grep -qx "$name" <<<"$REGISTERED"; then
        echo "skip    $name (already registered)"
        skipped=$((skipped + 1))
        continue
    fi
    payload=$(python3 -c "
import json, sys
print(json.dumps({
    'name': sys.argv[1],
    'version': '1.0.0',
    'description': sys.argv[2],
    'source': {'source': 'git-subdir', 'url': sys.argv[3], 'path': f'agents-skills/{sys.argv[1]}'},
}))" "$name" "$desc" "$REPO_URL")
    if curl -sf --max-time 15 -X POST "${AUTH[@]}" "${BASE_URL}/claude-code/plugins" \
            -d "$payload" > /dev/null; then
        if curl -sf --max-time 15 -X POST "${AUTH[@]}" "${BASE_URL}/claude-code/plugins/${name}/enable" > /dev/null; then
            echo "added   $name (registered + enabled)"
            added=$((added + 1))
        else
            echo "WARN    $name registered but enable failed"
            failed=$((failed + 1))
        fi
    else
        echo "FAIL    $name (register rejected)"
        failed=$((failed + 1))
    fi
done

echo ""
echo "Done: ${added} added, ${skipped} already registered, ${failed} failed."
if (( failed > 0 )); then
    exit 1
fi
