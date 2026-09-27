#!/usr/bin/env bash
# =====================================================================
# backup-nas.sh — multi-host NAS backup engine
# (plan: docs/backup-audit-2026-09-26.md v3, §3.1–§3.5)
# =====================================================================
# Host-agnostic: behavior is fully driven by a per-host config file
# (scripts/backup-hosts/<host>.json). The same script runs on every
# machine; each host writes ONLY into its own subdirectory of the
# shared NAS share (collision rules: plan §3.5).
#
# Usage:
#   backup-nas.sh daily
#   backup-nas.sh weekly
#   backup-nas.sh one-off <label>
#
# Options:
#   --root DIR      use DIR as the NAS root instead of mounting (local testing)
#   --host ID       host id (default: $(hostname -s))
#   --config FILE   host config (default: scripts/backup-hosts/<host>.json)
#   --dry-run       generate + hash + report; no commit, no prune, no hedge
#   --force         ignore change detection (re-store everything)
#   --skip-mount    fail if the NAS is not already mounted
#
# Guarantees:
#   * staging + commit: artifacts are rsynced to .staging-<run>/ and only
#     renamed into <run>/ after all items are processed; manifest.json is
#     the LAST write. A run dir without manifest.json is uncommitted and
#     is ignored by prune/restore.
#   * change detection: an item whose sha256 matches the last stored copy
#     is not re-stored (status=unchanged, same_as=<run>); restore follows
#     the chain.
#   * prune: only committed runs (with manifest.json), only under this
#     host's own subdirectory; one-off runs are never pruned.
#   * flock: one run at a time per host.
#   * mirrors (rsync --delete straight into <host>/mirrors/<name>/) are
#     safe on crash: the source is authoritative, so an interrupted
#     mirror is at worst incomplete until the next run — nothing is lost.
#
# Exit codes: 0 = all items ok · 1 = some items failed · 2 = setup/mount error
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup-lib.sh
source "$SCRIPT_DIR/backup-lib.sh"

MODE="" LABEL="" ROOT_OVERRIDE="" HOST_ARG="" CONFIG_ARG=""
DRY_RUN=0 FORCE=0 SKIP_MOUNT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    daily|weekly) MODE="$1"; shift ;;
    one-off) MODE="one-off"; LABEL="${2:?one-off requires a label}"; shift 2 ;;
    --root) ROOT_OVERRIDE="${2:?}"; shift 2 ;;
    --host) HOST_ARG="${2:?}"; shift 2 ;;
    --config) CONFIG_ARG="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --skip-mount) SKIP_MOUNT=1; shift ;;
    -h|--help) sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$MODE" ]] || { echo "usage: backup-nas.sh <daily|weekly|one-off LABEL> [options] — see --help" >&2; exit 2; }

resolve_config "$CONFIG_ARG" "$HOST_ARG"
LOGFILE="$STATE_DIR/backup-nas.log"
log() { echo "[$(date '+%F %T')] [$HOST_ID] $*" | tee -a "$LOGFILE" >&2; }

# --- lock: one run at a time per host ------------------------------------
LOCKFILE="$STATE_DIR/backup-nas-${HOST_ID}.lock"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  log "another backup run is in progress (lock: $LOCKFILE) — exiting"
  exit 2
fi

ensure_nas_root "$ROOT_OVERRIDE" "$SKIP_MOUNT"
HOST_ROOT="$NAS_ROOT/$HOST_ID"
mkdir -p "$HOST_ROOT"

# --- free-space guard: protect the NAS disk from an unbounded run ----------
MIN_FREE_KB="$(jq -r '.min_free_kb // 5242880' "$CONFIG")"   # default 5 GB
require_free_space "$HOST_ROOT" $(( MIN_FREE_KB * 1024 ))

STAMP="$(date +%Y%m%d-%H%M%S)"
case "$MODE" in
  daily)   RUN_ID="daily-${STAMP}" ;;
  weekly)  RUN_ID="weekly-${STAMP}" ;;
  one-off) RUN_ID="one-off-${LABEL}-${STAMP}" ;;
esac
WORK="$(mktemp -d "${TMPDIR:-/tmp}/backup-nas-${HOST_ID}-XXXXXX")"
ENTRIES="$WORK.entries.jsonl"
: > "$ENTRIES"
FAILURES=0
QDRANT_RESP="/tmp/qdrant-snap-resp.$$.json"
cleanup() {
  rm -rf "$ENTRIES" "$QDRANT_RESP" 2>/dev/null || true
  # keep the work dir on dry-run for inspection
  if [[ "${DRY_RUN:-0}" -ne 1 ]]; then rm -rf "$WORK" 2>/dev/null || true; fi
}
trap cleanup EXIT

log "=== backup-nas ${MODE} ${LABEL:-} starting (run $RUN_ID, root: $NAS_ROOT, dry_run=$DRY_RUN force=$FORCE) ==="

# --- item list for this mode (one-off = daily + weekly) --------------------
DAILY_ITEMS="$(jq -c '.daily // []' "$CONFIG")"
WEEKLY_ITEMS="$(jq -c '.weekly // []' "$CONFIG")"
case "$MODE" in
  daily)   ITEMS_JSON="$DAILY_ITEMS" ;;
  weekly)  ITEMS_JSON="$WEEKLY_ITEMS" ;;
  one-off) ITEMS_JSON="$(jq -cn --argjson d "$DAILY_ITEMS" --argjson w "$WEEKLY_ITEMS" '$d + $w')" ;;
esac
ITEM_COUNT="$(jq 'length' <<<"$ITEMS_JSON")"
log "items: $ITEM_COUNT"

# --- change detection --------------------------------------------------------
# prev_info <item-name> -> "<sha256> <run_id>" of the last STORED copy,
# following the unchanged (same_as) chain across manifests. Empty if none.
prev_info() {
  local name="$1" m entry same status hops
  while IFS= read -r m; do
    entry="$(item_entry "$m" "$name" || true)"
    [[ -z "$entry" ]] && continue
    hops=0
    while (( hops < 30 )); do
      status="$(jq -r '.status // empty' <<<"$entry")"
      if [[ "$status" == "stored" ]]; then
        jq -r '"\(.sha256) \(.run_id)"' <<<"$entry"
        return 0
      elif [[ "$status" == "unchanged" ]]; then
        same="$(jq -r '.same_as // empty' <<<"$entry")"
        [[ -n "$same" ]] || return 0
        m="$(manifest_for_run "$same" || true)"
        [[ -n "$m" ]] || return 0
        entry="$(item_entry "$m" "$name" || true)"
        [[ -n "$entry" ]] || return 0
      else
        return 0
      fi
      hops=$((hops+1))
    done
    return 0
  done < <(committed_manifests)
  return 0
}

# git_head_of_prev -> git_head of the newest manifest that has one (or "")
git_head_of_prev() {
  local m h
  while IFS= read -r m; do
    h="$(jq -r '.git_head // empty' "$m" 2>/dev/null || true)"
    if [[ -n "$h" ]]; then echo "$h"; return 0; fi
  done < <(committed_manifests)
  return 0
}

append_entry() { # name type status sha size path [same_as] [note]
  local name=$1 type=$2 status=$3 sha=$4 size=$5 path=${6:-} same_as=${7:-} note=${8:-}
  jq -cn \
    --arg n "$name" --arg t "$type" --arg s "$status" --arg h "$sha" \
    --arg sz "$size" --arg p "$path" --arg sa "$same_as" --arg nt "$note" \
    --arg rid "$RUN_ID" \
    '{name:$n,type:$t,status:$s,run_id:$rid,
      sha256:(if $h=="" then null else $h end),
      size_bytes:(if $sz=="" then null else ($sz|tonumber) end),
      path:(if $p=="" then null else $p end),
      same_as:(if $sa=="" then null else $sa end),
      note:(if $nt=="" then null else $nt end)}' >> "$ENTRIES"
}

mark_failed() { # name type note
  log "  $1: FAILED — $3"
  append_entry "$1" "$2" failed "" "" "" "" "$3"
  FAILURES=$((FAILURES+1))
}

# maybe_store <file> <item-name> <type>
# Hash the generated artifact; if it matches the last stored copy, drop it
# (unchanged); otherwise keep it for the staging rsync.
maybe_store() {
  local f="$1" name="$2" type="$3"
  local sha prev prev_sha prev_run size rel
  sha="$(sha256sum "$f" | cut -d' ' -f1)"
  prev="$(prev_info "$name" || true)"
  if [[ -n "$prev" && "$FORCE" -eq 0 ]]; then
    prev_sha="${prev%% *}"
    if [[ "$prev_sha" == "$sha" ]]; then
      prev_run="${prev#* }"
      append_entry "$name" "$type" unchanged "$sha" "" "" "$prev_run"
      rm -f "$f"
      log "  $name: unchanged — not re-stored (same as $prev_run)"
      return 0
    fi
  fi
  size="$(stat -c%s "$f")"
  rel="${f#"$WORK"/}"
  append_entry "$name" "$type" stored "$sha" "$size" "$rel"
  log "  $name: stored ($(numfmt --to=iec "$size") B)"
}

# --- item generators ----------------------------------------------------------
# Each generator: $1 = item JSON. Generates artifacts under $WORK and
# records manifest entries (stored / unchanged / failed / skipped).

gen_qdrant() {
  local item="$1"
  local url="${QDRANT_HOST_URL:-http://localhost:6333}"
  local key="${QDRANT_ADMIN_API_KEY:-}"
  if [[ -z "$key" ]]; then
    mark_failed "qdrant" qdrant_snapshot "QDRANT_ADMIN_API_KEY not set"
    return 0
  fi
  local cols
  cols="$(curl -sf -H "api-key: $key" "$url/collections" | jq -r '.result.collections[].name' || true)"
  if [[ -z "$cols" ]]; then
    mark_failed "qdrant" qdrant_snapshot "no collections at $url (qdrant down?)"
    return 0
  fi
  local col http snap dest
  for col in $cols; do
    http="$(curl -s -o "$QDRANT_RESP" -w '%{http_code}' -H "api-key: $key" -X POST "$url/collections/${col}/snapshots")"
    if [[ "$http" != "200" ]]; then
      mark_failed "qdrant/$col" qdrant_snapshot "snapshot HTTP $http: $(head -c 200 "$QDRANT_RESP" 2>/dev/null)"
      continue
    fi
    snap="$(jq -r '.result.name // empty' "$QDRANT_RESP")"
    if [[ -z "$snap" ]]; then
      snap="$(basename "$(jq -r '.result | select(type == "string")' "$QDRANT_RESP" 2>/dev/null)")"
    fi
    if [[ -z "$snap" ]]; then
      mark_failed "qdrant/$col" qdrant_snapshot "could not parse snapshot name"
      continue
    fi
    dest="$WORK/qdrant/${col}-${STAMP}.snapshot"
    mkdir -p "$WORK/qdrant"
    if docker exec qdrant cat "/qdrant/snapshots/${col}/${snap}" > "$dest" 2>/dev/null && [[ -s "$dest" ]]; then
      maybe_store "$dest" "qdrant/$col" qdrant_snapshot
    else
      rm -f "$dest"
      mark_failed "qdrant/$col" qdrant_snapshot "docker exec cat failed"
    fi
  done
}

gen_tar() {
  local item="$1"
  local name; name="$(jq -r '.name' <<<"$item")"
  local -a sources=()
  while IFS= read -r p; do sources+=("$p"); done < <(jq -r '.sources[]' <<<"$item")
  local -a existing=()
  local p
  for p in "${sources[@]}"; do
    if [[ -e "$p" ]]; then existing+=("$p"); else log "  $name: WARNING source missing: $p"; fi
  done
  if [[ ${#existing[@]} -eq 0 ]]; then
    append_entry "$name" tar skipped "" "" "" "" "no sources present"
    log "  $name: no sources present — skipped"
    return 0
  fi
  local -a rels=()
  for p in "${existing[@]}"; do rels+=("${p#/}"); done
  local out="$WORK/${name}-${STAMP}.tar.gz"
  # --ignore-failed-read: unreadable files (e.g. root-owned container data)
  # are skipped with a warning instead of failing the whole archive
  if tar -czf "$out" --ignore-failed-read -C / "${rels[@]}"; then
    maybe_store "$out" "$name" tar
  else
    rm -f "$out"
    mark_failed "$name" tar "tar failed"
  fi
}

gen_mysql_dump() {
  local item="$1"
  local name db user pass host
  name="$(jq -r '.name' <<<"$item")"
  db="$(jq -r '.database' <<<"$item")"
  local user_env pass_env host_env
  user_env="$(jq -r '.user_env' <<<"$item")"
  pass_env="$(jq -r '.password_env' <<<"$item")"
  host_env="$(jq -r '.host_env // "MYSQL_DB_HOST"' <<<"$item")"
  user="${!user_env:-}"; pass="${!pass_env:-}"; host="${!host_env:-}"
  if [[ -z "$user" || -z "$pass" || -z "$host" ]]; then
    mark_failed "$name" mysql_dump "missing env vars (${user_env}/${pass_env}/${host_env})"
    return 0
  fi
  local out="$WORK/mysql/${db}-${STAMP}.sql.gz"
  mkdir -p "$WORK/mysql"
  local errfile="$WORK/.mysql-err-${db}"
  if MYSQL_PWD="$pass" mysqldump -h "$host" -u "$user" \
      --single-transaction --routines --triggers --events --set-gtid-purged=OFF \
      --databases "$db" 2>"$errfile" | gzip > "$out" && [[ -s "$out" ]]; then
    maybe_store "$out" "$name" mysql_dump
  else
    rm -f "$out"
    mark_failed "$name" mysql_dump "$(head -1 "$errfile" 2>/dev/null || echo 'dump failed')"
  fi
}

gen_pg_dump() {
  local item="$1"
  local name container user dumpall
  name="$(jq -r '.name' <<<"$item")"
  container="$(jq -r '.container' <<<"$item")"
  user="$(jq -r '.user' <<<"$item")"
  dumpall="$(jq -r '.dumpall // true' <<<"$item")"
  local out="$WORK/${name}-${STAMP}.sql.gz"
  local errfile="$WORK/.pg-err-${name}"
  if [[ "$dumpall" == "true" ]]; then
    if docker exec "$container" pg_dumpall -U "$user" 2>"$errfile" | gzip > "$out" && [[ -s "$out" ]]; then
      maybe_store "$out" "$name" pg_dump
    else
      rm -f "$out"
      mark_failed "$name" pg_dump "$(head -1 "$errfile" 2>/dev/null || echo 'pg_dumpall failed')"
    fi
  else
    local db; db="$(jq -r '.database' <<<"$item")"
    if docker exec "$container" pg_dump -U "$user" "$db" 2>"$errfile" | gzip > "$out" && [[ -s "$out" ]]; then
      maybe_store "$out" "$name" pg_dump
    else
      rm -f "$out"
      mark_failed "$name" pg_dump "$(head -1 "$errfile" 2>/dev/null || echo 'pg_dump failed')"
    fi
  fi
}

gen_clickhouse_backup() {
  local item="$1"
  local name container
  name="$(jq -r '.name' <<<"$item")"
  container="$(jq -r '.container' <<<"$item")"
  local dbs bname
  dbs="$(jq -r '.databases | join(", ")' <<<"$item")"
  bname="$(echo "$name" | tr '/' '_')-${STAMP}"
  local out="$WORK/${name//\//_}-${STAMP}.tar.gz"
  local stage="$WORK/.ch-backups"
  mkdir -p "$stage/backups"
  local errfile="$WORK/.ch-err-${name//\//_}"
  if docker exec "$container" clickhouse client --query \
      "BACKUP DATABASE ${dbs} TO Disk('backups', '${bname}')" 2>"$errfile"; then
    if docker cp "${container}:/var/lib/clickhouse/backups/${bname}" "$stage/backups/" 2>>"$errfile"; then
      tar -czf "$out" -C "$stage" backups
      # clean up the container-side copy (the data volume would bloat)
      docker exec "$container" rm -rf "/var/lib/clickhouse/backups/${bname}" 2>/dev/null || true
      maybe_store "$out" "$name" clickhouse_backup
    else
      rm -f "$out"
      mark_failed "$name" clickhouse_backup "$(head -1 "$errfile" 2>/dev/null || echo 'docker cp failed')"
    fi
  else
    mark_failed "$name" clickhouse_backup "$(head -1 "$errfile" 2>/dev/null || echo 'BACKUP query failed (backups.xml mounted?)')"
  fi
  rm -rf "$stage"
}

gen_rsync() {
  local item="$1"
  local name source
  name="$(jq -r '.name' <<<"$item")"
  source="$(jq -r '.source' <<<"$item")"
  if [[ ! -d "$source" ]]; then
    append_entry "$name" rsync skipped "" "" "" "" "source missing: $source"
    log "  $name: source missing ($source) — skipped"
    return 0
  fi
  local -a excl=()
  local e
  while IFS= read -r e; do [[ -n "$e" ]] && excl+=("--exclude=$e"); done < <(jq -r '.exclude[]?' <<<"$item")
  local dest="$WORK/${name}"
  if rsync "${RSYNC_FLAGS[@]}" "${excl[@]+"${excl[@]}"}" "$source/" "$dest/"; then
    local size
    size="$(du -sb "$dest" | cut -f1)"
    append_entry "$name" rsync stored "" "$size" "$name/"
    log "  $name: rsynced ($(numfmt --to=iec "$size") B)"
  else
    rm -rf "$dest"
    mark_failed "$name" rsync "rsync failed"
  fi
}

gen_file() {
  local item="$1"
  local name source container cpath
  name="$(jq -r '.name' <<<"$item")"
  source="$(jq -r '.source // empty' <<<"$item")"
  container="$(jq -r '.container // empty' <<<"$item")"
  cpath="$(jq -r '.container_path // empty' <<<"$item")"
  local dest="$WORK/${name}"
  if [[ -n "$container" && -n "$cpath" ]]; then
    # file is unreadable on the host (owned by a container user) — pull it
    # out of the running container instead
    if docker cp "${container}:${cpath}" "$dest" >/dev/null 2>&1 && [[ -s "$dest" ]]; then
      maybe_store "$dest" "$name" file
    else
      rm -f "$dest"
      mark_failed "$name" file "docker cp from ${container} failed"
    fi
    return 0
  fi
  if [[ ! -f "$source" ]]; then
    append_entry "$name" file skipped "" "" "" "" "source missing: $source"
    log "  $name: source missing ($source) — skipped"
    return 0
  fi
  # cp without -p: the source may be owned by a container user (e.g.
  # grafana.db); preserving ownership would fail as non-root
  if cp "$source" "$dest"; then
    maybe_store "$dest" "$name" file
  else
    rm -f "$dest"
    mark_failed "$name" file "copy failed"
  fi
}

gen_git_bundle() {
  local item="$1"
  local name repo branch head
  name="$(jq -r '.name' <<<"$item")"
  repo="$(jq -r '.repo' <<<"$item")"
  branch="$(jq -r '.branch // "main"' <<<"$item")"
  if [[ ! -d "$repo/.git" ]]; then
    mark_failed "$name" git_bundle "not a git repo: $repo"
    return 0
  fi
  head="$(git -C "$repo" rev-parse "refs/heads/${branch}" 2>/dev/null || true)"
  if [[ -z "$head" ]]; then
    mark_failed "$name" git_bundle "branch not found: $branch"
    return 0
  fi
  if [[ "$FORCE" -eq 0 ]]; then
    local prev_head
    prev_head="$(git_head_of_prev || true)"
    if [[ -n "$prev_head" && "$prev_head" == "$head" ]]; then
      local prev_run
      prev_run="$(run_id_of "$(latest_manifest || true)" 2>/dev/null || true)"
      append_entry "$name" git_bundle unchanged "" "" "" "$prev_run"
      log "  $name: HEAD unchanged (${head:0:12}) — not re-bundled (same as ${prev_run:-?})"
      return 0
    fi
  fi
  local out="$WORK/${name}-${STAMP}.bundle"
  if ( cd "$repo" && git bundle create "$out" "refs/heads/${branch}" ) >/dev/null 2>&1; then
    maybe_store "$out" "$name" git_bundle
  else
    rm -f "$out"
    mark_failed "$name" git_bundle "git bundle create failed"
  fi
}

gen_mirror() {
  local item="$1"
  local name source
  name="$(jq -r '.name' <<<"$item")"
  source="$(jq -r '.source' <<<"$item")"
  if [[ ! -d "$source" ]]; then
    mark_failed "$name" mirror "source missing: $source"
    return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    append_entry "$name" mirror skipped "" "" "mirrors/${name}/" "" "dry-run: not synced"
    log "  $name: mirror (dry-run — not synced)"
    return 0
  fi
  local -a excl=()
  local e
  while IFS= read -r e; do [[ -n "$e" ]] && excl+=("--exclude=$e"); done < <(jq -r '.exclude[]?' <<<"$item")
  local dest="$HOST_ROOT/mirrors/${name}"
  mkdir -p "$dest"
  local stats
  # --ignore-errors: VM cache dirs contain root-owned/ephemeral files;
  # partial mirror is still useful (the source stays authoritative)
  if stats="$(rsync "${RSYNC_FLAGS[@]}" --delete --ignore-errors --stats "${excl[@]+"${excl[@]}"}" "$source/" "$dest/" 2>&1)"; then
    local bytes
    bytes="$(awk -F': ' '/^Total transferred file size/ {print $2}' <<<"$stats" | grep -oE '^[0-9]+' || true)"
    append_entry "$name" mirror updated "${bytes:-0}" "" "mirrors/${name}/"
    log "  $name: mirror updated (${bytes:-0} B transferred)"
  else
    mark_failed "$name" mirror "rsync failed: $(tail -1 <<<"$stats" 2>/dev/null)"
  fi
}

dispatch_item() {
  local item="$1"
  local type; type="$(jq -r '.type' <<<"$item")"
  case "$type" in
    qdrant_snapshot)   gen_qdrant "$item" ;;
    tar)               gen_tar "$item" ;;
    mirror)            gen_mirror "$item" ;;
    rsync)             gen_rsync "$item" ;;
    file)              gen_file "$item" ;;
    mysql_dump)        gen_mysql_dump "$item" ;;
    pg_dump)           gen_pg_dump "$item" ;;
    clickhouse_backup) gen_clickhouse_backup "$item" ;;
    git_bundle)        gen_git_bundle "$item" ;;
    *) mark_failed "$(jq -r '.name // "unknown"' <<<"$item")" "$type" "unknown item type" ;;
  esac
}

# --- run the items ------------------------------------------------------------
STARTED="$(date -u +%FT%TZ)"
i=0
while IFS= read -r item; do
  i=$((i+1))
  log "[$i/$ITEM_COUNT] $(jq -c . <<<"$item")"
  before="$(wc -l < "$ENTRIES")"
  dispatch_item "$item" || true
  after="$(wc -l < "$ENTRIES")"
  # safety net: a generator that died without recording anything
  if [[ "$after" -le "$before" ]]; then
    mark_failed "$(jq -r '.name // "unknown"' <<<"$item")" "$(jq -r '.type' <<<"$item")" "generator exited without recording"
  fi
done < <(jq -c '.[]' <<<"$ITEMS_JSON")

# --- manifest (written LAST = the commit marker) ------------------------------
GIT_REPO="$(jq -r '.[] | select(.type=="git_bundle") | .repo' <<<"$ITEMS_JSON" | head -1 || true)"
GIT_HEAD=""
if [[ -n "$GIT_REPO" && -d "$GIT_REPO" ]]; then
  GIT_HEAD="$(git -C "$GIT_REPO" rev-parse HEAD 2>/dev/null || true)"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  write_manifest "$WORK/manifest.json"
  log "dry-run complete (work dir kept for inspection: $WORK)"
  log "=== backup-nas ${MODE} dry-run done: $FAILURES failure(s) ==="
  exit "$FAILURES"
fi

# --- verify: re-hash every stored artifact on the NAS vs the manifest -------
# CIFS can corrupt/drop data on a dead session; this catches it. A FAILED
# verify means re-run the backup (the run is suspect).
verify_run() {
  local manifest="$1" run_dir="$2"
  local total=0 bad=0 item status path sha f actual
  while IFS= read -r item; do
    status="$(jq -r '.status // empty' <<<"$item")"
    path="$(jq -r '.path // empty' <<<"$item")"
    sha="$(jq -r '.sha256 // empty' <<<"$item")"
    # only verify real single-file artifacts: status=stored, has a real sha,
    # and the path is a file (mirrors/rsync dirs end with / and have no sha)
    [[ "$status" == "stored" && -n "$path" && -n "$sha" && "$path" != */ ]] || continue
    total=$((total+1))
    f="$run_dir/$path"
    if [[ ! -f "$f" ]]; then
      echo "  VERIFY: MISSING $path" >&2; bad=$((bad+1)); continue
    fi
    actual="$(sha256sum "$f" | cut -d' ' -f1)"
    if [[ "$actual" != "$sha" ]]; then
      echo "  VERIFY: MISMATCH $path (want ${sha:0:12}.. got ${actual:0:12}..)" >&2
      bad=$((bad+1))
    fi
  done < <(jq -c '.items[]' "$manifest")
  if (( bad == 0 )); then
    log "verify OK ($total stored artifact(s) intact)"
    return 0
  fi
  log "verify FAILED ($bad/$total artifacts corrupted — re-run the backup)"
  return 1
}

# --- commit --------------------------------------------------------------------
if [[ "$FAILURES" -gt 0 ]]; then
  log "WARNING: $FAILURES item(s) failed — committing partial run (failures recorded in manifest)"
fi

STAGING="$HOST_ROOT/.staging-${RUN_ID}"
if rsync "${RSYNC_FLAGS[@]}" "$WORK/" "$STAGING/"; then
  mv "$STAGING" "$HOST_ROOT/${RUN_ID}"
  log "committed run dir: ${RUN_ID}"
else
  log "ERROR: staging rsync failed — run NOT committed"
  rm -rf "$STAGING"
  exit 1
fi
write_manifest "$HOST_ROOT/${RUN_ID}/manifest.json"
log "manifest written (commit marker)"

# post-run integrity verify (catch CIFS corruption before we trust the run)
if ! verify_run "$HOST_ROOT/${RUN_ID}/manifest.json" "$HOST_ROOT/${RUN_ID}"; then
  log "ERROR: post-run verify failed — this run is suspect; re-run the backup"
  exit 1
fi

# --- prune ----------------------------------------------------------------------
prune_tier() {
  local tier="$1" keep="$2"
  local runs
  runs="$(find "$HOST_ROOT" -maxdepth 1 -mindepth 1 -type d -name "${tier}-*" 2>/dev/null | while read -r d; do
      [[ -f "$d/manifest.json" ]] && echo "$d"
    done | sort)"
  local count=0
  [[ -n "$runs" ]] && count="$(wc -l <<<"$runs" | tr -d ' ')"
  if (( count > keep )); then
    local to_delete
    to_delete="$(head -n $((count - keep)) <<<"$runs")"
    local d
    while IFS= read -r d; do
      [[ -n "$d" ]] || continue
      rm -rf "$d"
      log "pruned: $(basename "$d")"
    done <<<"$to_delete"
  fi
}

DAILY_KEEP="$(jq -r '.retention.daily // 14' "$CONFIG")"
WEEKLY_KEEP="$(jq -r '.retention.weekly // 2' "$CONFIG")"
prune_tier "daily" "$DAILY_KEEP"
prune_tier "weekly" "$WEEKLY_KEEP"
# one-off runs are never pruned
# stale staging dirs from crashed runs (>1 day old)
find "$HOST_ROOT" -maxdepth 1 -name ".staging-*" -mtime +1 -exec rm -rf {} + 2>/dev/null || true

# --- local hedge (daily only) ------------------------------------------------------
if [[ "$MODE" == "daily" ]]; then
  HEDGE_ENABLED="$(jq -r '.local_hedge.enabled // false' "$CONFIG")"
  if [[ "$HEDGE_ENABLED" == "true" ]]; then
    HEDGE_DIR="$(jq -r '.local_hedge.dir' "$CONFIG")"
    HEDGE_KEEP="$(jq -r '.local_hedge.keep // 2' "$CONFIG")"
    mkdir -p "$HEDGE_DIR"
    cp -a "$HOST_ROOT/${RUN_ID}" "$HEDGE_DIR/"
    hedge_runs="$(find "$HEDGE_DIR" -maxdepth 1 -mindepth 1 -type d -name "daily-*" 2>/dev/null | while read -r d; do
        [[ -f "$d/manifest.json" ]] && echo "$d"
      done | sort)"
    hedge_count=0
    [[ -n "$hedge_runs" ]] && hedge_count="$(wc -l <<<"$hedge_runs" | tr -d ' ')"
    if (( hedge_count > HEDGE_KEEP )); then
      head -n $((hedge_count - HEDGE_KEEP)) <<<"$hedge_runs" | while IFS= read -r d; do
        [[ -n "$d" ]] || continue
        rm -rf "$d"
        log "pruned hedge: $(basename "$d")"
      done
    fi
    log "hedge: copied ${RUN_ID} → $HEDGE_DIR (keep $HEDGE_KEEP)"
  fi
fi

log "=== backup-nas ${MODE} complete: run ${RUN_ID}, $FAILURES failure(s) ==="
if [[ "$FAILURES" -gt 0 ]]; then
  exit 1
fi
exit 0