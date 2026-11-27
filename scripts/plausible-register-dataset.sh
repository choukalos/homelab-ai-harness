#!/usr/bin/env bash
# plausible-register-dataset.sh — register the Plausible dataset in the
# data-hub v2 generic-datasets registry (idempotent: skips if it exists).
#
# Registers the `plausible` dataset: source_pattern `plausible-*.csv` (the
# files plausible-export.sh drops into the inbox), a fixed column_map (so the
# schema is explicit, not inferred), and key_columns (date, site_id) so
# re-exports upsert in place instead of duplicating.
#
# See docs/data-hub-ingest.md for the general pattern.
set -euo pipefail

DATAHUB_URL="${DATAHUB_URL:-http://192.168.4.54:8100}"
NAME="plausible"

# Idempotency: skip if the dataset is already registered.
exists=$(curl -sf "${DATAHUB_URL}/api/datasets" 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(any(x['name']=='${NAME}' for x in d.get('datasets',[])))" 2>/dev/null || echo "False")
if [ "$exists" = "True" ]; then
  echo "dataset '${NAME}' already registered at ${DATAHUB_URL} — nothing to do"
  exit 0
fi

resp=$(curl -sf -X POST "${DATAHUB_URL}/api/datasets" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "plausible",
    "description": "Plausible web analytics: daily aggregates (pageviews, unique visitors, custom events) per site per day. Source: Plausible ClickHouse events_v2, exported by homelab/scripts/plausible-export.sh.",
    "source_pattern": "plausible-*.csv",
    "delimiter": ",",
    "has_header": 1,
    "column_map": {
      "date": "date DATE",
      "site_id": "site_id BIGINT",
      "domain": "domain VARCHAR(255)",
      "pageviews": "pageviews BIGINT",
      "unique_visitors": "unique_visitors BIGINT",
      "custom_events": "custom_events BIGINT"
    },
    "key_columns": ["date", "site_id"]
  }') || { echo "ERROR: dataset registration failed (data-hub at ${DATAHUB_URL} up?)" >&2; exit 1; }

echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"registered dataset '{d['name']}' -> {d['target_table']} (pattern {d['source_pattern']})\")"
echo "next export (plausible-export.sh) will be ingested into $(echo "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['target_table'])")"
