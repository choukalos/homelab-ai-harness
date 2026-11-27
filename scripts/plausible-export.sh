#!/usr/bin/env bash
# plausible-export.sh — export Plausible daily analytics to the data-hub inbox.
#
# Queries Plausible's ClickHouse (events_v2) for daily aggregates per site
# (pageviews, unique visitors, custom events), joins the site_id -> domain
# mapping from Plausible's Postgres, and writes a CSV into the data-hub
# generic-datasets inbox. The data-hub watcher (v2a) picks the file up by
# source_pattern and upserts it into hub.ds_plausible — idempotent, keyed on
# (date, site_id), so re-running for the same day updates in place.
#
# This is the first NON-FINANCE consumer of the data-hub v2 generic-datasets
# ingest framework. See docs/data-hub-ingest.md for the general pattern and
# how to add more datasets (projects/reports/etc).
#
# Config (env overrides):
#   INBOX_DIR     data-hub generic inbox (default /home/chuck/data/finance/inbox)
#   DAYS          lookback window for the daily aggregates (default 90)
#   OUT_NAME      output CSV basename (default plausible-daily-YYYY-MM-DD.csv)
#   CH_CONTAINER  Plausible ClickHouse container (default plausible-events-db)
#   PG_CONTAINER  Plausible Postgres container (default plausible-db)
#   PG_USER/PG_DB Plausible Postgres user/db (default plausible/plausible)
set -euo pipefail

INBOX_DIR="${INBOX_DIR:-/home/chuck/data/finance/inbox}"
DAYS="${DAYS:-90}"
OUT_NAME="${OUT_NAME:-plausible-daily-$(date -u +%Y-%m-%d).csv}"
CH_CONTAINER="${CH_CONTAINER:-plausible-events-db}"
PG_CONTAINER="${PG_CONTAINER:-plausible-db}"
PG_USER="${PG_USER:-plausible}"
PG_DB="${PG_DB:-plausible}"
CH_DB="${CH_DB:-plausible}"

# --- site_id -> domain mapping (Plausible Postgres), TSV ---------------------
domains=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" \
  -t -A -F $'\t' -c "SELECT id, domain FROM sites ORDER BY id" 2>/dev/null) \
  || { echo "ERROR: could not query Plausible Postgres (sites table)" >&2; exit 1; }

# --- daily aggregates (Plausible ClickHouse), TSV ----------------------------
# pageview = a page view; unique_visitors = distinct sessions; custom_events =
# any non-pageview event (goals, etc). One row per (date, site_id).
aggregates=$(docker exec "$CH_CONTAINER" clickhouse client --query "
  SELECT toDate(timestamp) AS date, site_id,
    countIf(name = 'pageview')      AS pageviews,
    uniq(session_id)                AS unique_visitors,
    countIf(name != 'pageview')     AS custom_events
  FROM ${CH_DB}.events_v2
  WHERE timestamp >= now() - INTERVAL ${DAYS} DAY
  GROUP BY date, site_id
  ORDER BY date, site_id" 2>/dev/null)

if [ -z "$aggregates" ]; then
  echo "WARNING: no events in the last ${DAYS} days — writing a header-only CSV" >&2
fi

# --- build the CSV ------------------------------------------------------------
mkdir -p "$INBOX_DIR"
{
  echo "date,site_id,domain,pageviews,unique_visitors,custom_events"
  declare -A DOMAIN=()
  while IFS=$'\t' read -r id domain; do
    [ -n "${id:-}" ] && DOMAIN["$id"]="$domain"
  done <<< "$domains"
  while IFS=$'\t' read -r d sid pv uv ce; do
    [ -z "${d:-}" ] && continue
    domain="${DOMAIN[$sid]:-unknown}"
    echo "$d,$sid,$domain,$pv,$uv,$ce"
  done <<< "$aggregates"
} > "$INBOX_DIR/$OUT_NAME"

rows=$(( $(wc -l < "$INBOX_DIR/$OUT_NAME") - 1 ))
echo "wrote $INBOX_DIR/$OUT_NAME ($rows data rows, last ${DAYS} days)"
echo "data-hub watcher will ingest it into hub.ds_plausible (key: date+site_id)"
