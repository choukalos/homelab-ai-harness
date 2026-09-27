#!/usr/bin/env bash
# =====================================================================
# backup-restore.sh — partial + full recovery from NAS backups
# (plan: docs/backup-audit-2026-09-26.md v3, §3.6)
# =====================================================================
# Reads the committed runs written by backup-nas.sh. manifest.json is
# the commit marker; sha256 is verified BEFORE any restore.
#
# Usage:
#   backup-restore.sh --list [--items]
#   backup-restore.sh --item <name> [--item <name> ...] [--from <run>]
#                     [--dry-run | --yes] [--test]
#   backup-restore.sh --full [--from <run>] [--target <dir>] [--yes]
#
#   --list            list committed runs (newest first)
#   --items           with --list: also show items of the latest run
#   --item NAME       restore one item (repeatable). NAME = manifest
#                     item name, e.g. mysql/homelab, qdrant/mem0_memories,
#                     env, ai-kb (live mirror), grafana.db, homelab-git
#   --from RUN        run id or unique prefix (default: newest run that
#                     has the item)
#   --dry-run         show what would happen (DEFAULT for live modes)
#   --yes             actually perform the destructive/live restore
#   --test            restore into a DISPOSABLE docker container and run
#                     a smoke query — NEVER touches live state
#   --full            restore everything from one run
#   --target DIR      with --full: stage everything into DIR and write
#                     RUNBOOK.md (fresh-disk / SSD-swap rebuild path)
#   --root DIR        use DIR as the NAS root (no mount) — local testing
#   --host ID         host id (default: $(hostname -s))
#   --config FILE     host config (default: scripts/backup-hosts/<host>.json)
#
# Restore audit log: ~/.local/state/backup-restore.log AND
# <nas>/<host>/restore-log/restore-<date>.log (when the NAS is reachable).
#
# Exit: 0 ok · 1 restore failure · 2 setup error
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup-lib.sh
source "$SCRIPT_DIR/backup-lib.sh"

ACTION="" ROOT_OVERRIDE="" HOST_ARG="" CONFIG_ARG="" FROM_RUN="" TARGET_DIR=""
YES=0 TEST=0 LIST_ITEMS=0
ITEMS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list) ACTION="list"; shift ;;
    --items) LIST_ITEMS=1; shift ;;
    --item) ITEMS+=("${2:?--item requires a name}"); shift 2 ;;
    --full) ACTION="full"; shift ;;
    --from) FROM_RUN="${2:?}"; shift 2 ;;
    --target) TARGET_DIR="${2:?}"; shift 2 ;;
    --dry-run) YES=0; shift ;;
    --yes) YES=1; shift ;;
    --test) TEST=1; shift ;;
    --root) ROOT_OVERRIDE="${2:?}"; shift 2 ;;
    --host) HOST_ARG="${2:?}"; shift 2 ;;
    --config) CONFIG_ARG="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

resolve_config "$CONFIG_ARG" "$HOST_ARG"
ensure_nas_root "$ROOT_OVERRIDE"
HOST_ROOT="$NAS_ROOT/$HOST_ID"
if [[ ! -d "$HOST_ROOT" ]]; then
  echo "ERROR: no backup data for host '$HOST_ID' under $HOST_ROOT" >&2
  exit 2
fi

# ---------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------
if [[ "$ACTION" == "list" ]]; then
  manifests="$(committed_manifests || true)"
  if [[ -z "$manifests" ]]; then
    echo "no committed runs under $HOST_ROOT"
    exit 0
  fi
  printf '%-30s %-8s %9s  %-20s %s\n' "RUN" "MODE" "SIZE" "ENDED" "NOTES"
  while IFS= read -r m; do
    rid="$(run_id_of "$m")"
    mode="$(jq -r '.mode // "?"' "$m")"
    ended="$(jq -r '.ended // "?"' "$m")"
    fails="$(jq -r '.failures // 0' "$m")"
    size="$(du -sh "$(dirname "$m")" 2>/dev/null | cut -f1)"
    note=""
    if [[ "$fails" -gt 0 ]]; then note="⚠ $fails failed item(s)"; fi
    printf '%-30s %-8s %9s  %-20s %s\n' "$rid" "$mode" "$size" "$ended" "$note"
  done <<<"$manifests"
  if [[ "$LIST_ITEMS" -eq 1 ]]; then
    latest="$(head -1 <<<"$manifests")"
    echo ""
    echo "items in $(run_id_of "$latest"):"
    jq -r '.items[] | "  \(.status | ascii_upcase)  \(.name)  \(.note // "")"' "$latest"
  fi
  exit 0
fi

# ---------------------------------------------------------------------
# per-type restore methods
# Each: $1=name $2=src (absolute path) $3=manifest entry $4=cfg item
# ---------------------------------------------------------------------

do_mysql() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local db user pass host
  db="$(jq -r '.database // empty' <<<"$cfg")"
  local ue pe he
  ue="$(jq -r '.user_env // empty' <<<"$cfg")"
  pe="$(jq -r '.password_env // empty' <<<"$cfg")"
  he="$(jq -r '.host_env // "MYSQL_DB_HOST"' <<<"$cfg")"
  user="${!ue:-}"; pass="${!pe:-}"; host="${!he:-}"

  if [[ "$TEST" -eq 1 ]]; then
    restore_log "  $name: TEST — loading dump into disposable mysql:8.0"
    local cname="bktest-mysql-$$" ok=0
    docker rm -f "$cname" >/dev/null 2>&1 || true
    if docker run -d --name "$cname" -e MYSQL_ROOT_PASSWORD=test -v "$src:/dump.sql.gz:ro" mysql:8.0 >/dev/null; then
      for _ in $(seq 1 45); do
        if docker exec "$cname" mysql -uroot -ptest -e "SELECT 1" >/dev/null 2>&1; then ok=1; break; fi
        sleep 1
      done
      if [[ "$ok" -eq 1 ]]; then
        local out
        if out="$(docker exec "$cname" sh -c 'gunzip -c /dump.sql.gz | mysql -uroot -ptest --force' 2>&1)"; then
          local ntables
          ntables="$(docker exec "$cname" mysql -uroot -ptest -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$db'" 2>/dev/null || echo '?')"
          restore_log "  $name: TEST OK — $ntables tables in $db"
          docker rm -f "$cname" >/dev/null 2>&1 || true
          return 0
        else
          restore_log "  $name: TEST FAILED: $(tail -3 <<<"$out")"
        fi
      fi
    fi
    docker rm -f "$cname" >/dev/null 2>&1 || true
    restore_log "  $name: TEST FAILED (container not ready?)"
    return 1
  fi

  if [[ "$YES" -eq 1 ]]; then
    restore_log "  $name: LIVE — loading dump into $db@$host (destructive: tables are replaced)"
    if gunzip -c "$src" | MYSQL_PWD="$pass" mysql -h "$host" -u "$user"; then
      restore_log "  $name: LIVE restore OK"
    else
      restore_log "  $name: LIVE restore FAILED"
      return 1
    fi
  else
    restore_log "  $name: DRY-RUN — would load $(du -h "$src" | cut -f1) dump into $db@$host (re-run with --yes to execute, or --test for a disposable check)"
  fi
}

do_pg() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local container user
  container="$(jq -r '.container // empty' <<<"$cfg")"
  user="$(jq -r '.user // empty' <<<"$cfg")"

  if [[ "$TEST" -eq 1 ]]; then
    restore_log "  $name: TEST — loading dumpall into disposable postgres:16-alpine"
    local cname="bktest-pg-$$" ok=0
    docker rm -f "$cname" >/dev/null 2>&1 || true
    if docker run -d --name "$cname" -e POSTGRES_PASSWORD=test -v "$src:/dump.sql.gz:ro" postgres:16-alpine >/dev/null; then
      for _ in $(seq 1 30); do
        if docker exec "$cname" pg_isready -U postgres >/dev/null 2>&1; then ok=1; break; fi
        sleep 1
      done
      if [[ "$ok" -eq 1 ]]; then
        local out
        if out="$(docker exec "$cname" sh -c 'gunzip -c /dump.sql.gz | psql -U postgres' 2>&1)"; then
          local ndb
          ndb="$(docker exec "$cname" psql -U postgres -tAc 'SELECT count(*) FROM pg_database' 2>/dev/null || echo '?')"
          restore_log "  $name: TEST OK — $ndb databases after load"
          docker rm -f "$cname" >/dev/null 2>&1 || true
          return 0
        else
          restore_log "  $name: TEST FAILED: $(tail -3 <<<"$out")"
        fi
      fi
    fi
    docker rm -f "$cname" >/dev/null 2>&1 || true
    restore_log "  $name: TEST FAILED (container not ready?)"
    return 1
  fi

  if [[ "$YES" -eq 1 ]]; then
    restore_log "  $name: LIVE — loading dumpall into $container (destructive: replaces databases/roles)"
    if gunzip -c "$src" | docker exec -i "$container" psql -U "$user" -d postgres; then
      restore_log "  $name: LIVE restore OK"
    else
      restore_log "  $name: LIVE restore FAILED"
      return 1
    fi
  else
    restore_log "  $name: DRY-RUN — would load dumpall into $container (re-run with --yes, or --test)"
  fi
}

do_clickhouse() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local container dbs
  container="$(jq -r '.container // empty' <<<"$cfg")"
  dbs="$(jq -r '.databases | join(", ")' <<<"$cfg")"
  local first_db="${dbs%%,*}"
  local bname
  bname="$(tar -tzf "$src" | grep -v '^backups/$' | head -1 | cut -d/ -f2)"

  if [[ "$TEST" -eq 1 ]]; then
    restore_log "  $name: TEST — restoring into disposable clickhouse container"
    local cname="bktest-ch-$$" ok=0
    local chcfg="$REPO_ROOT/plausible/clickhouse/backups.xml"
    local tmp; tmp="$(mktemp -d)"
    tar -xzf "$src" -C "$tmp"
    docker rm -f "$cname" >/dev/null 2>&1 || true
    if [[ -f "$chcfg" ]] && docker run -d --name "$cname" \
        -v "$chcfg:/etc/clickhouse-server/config.d/backups.xml:ro" \
        clickhouse/clickhouse-server:24.12-alpine >/dev/null; then
      for _ in $(seq 1 60); do
        if docker exec "$cname" clickhouse client --query "SELECT 1" >/dev/null 2>&1; then ok=1; break; fi
        sleep 1
      done
      if [[ "$ok" -eq 1 ]] && docker cp "$tmp/backups/${bname}" "${cname}:/var/lib/clickhouse/backups/"; then
        # docker cp lands root-owned; the CH server process runs as uid 101
        docker exec "$cname" chown -R 101:101 "/var/lib/clickhouse/backups/${bname}" 2>/dev/null || true
        local out
        if out="$(docker exec "$cname" clickhouse client --query "RESTORE DATABASE ${dbs} FROM Disk('backups', '${bname}')" 2>&1)"; then
          local ntables
          ntables="$(docker exec "$cname" clickhouse client -q "SELECT count(*) FROM system.tables WHERE database='${first_db}'" 2>/dev/null || echo '?')"
          restore_log "  $name: TEST OK — restored ($ntables tables in $first_db)"
          docker rm -f "$cname" >/dev/null 2>&1 || true
          rm -rf "$tmp"
          return 0
        else
          restore_log "  $name: TEST FAILED: $(tail -3 <<<"$out")"
        fi
      fi
    fi
    docker rm -f "$cname" >/dev/null 2>&1 || true
    rm -rf "$tmp"
    restore_log "  $name: TEST FAILED (container not ready?)"
    return 1
  fi

  if [[ "$YES" -eq 1 ]]; then
    restore_log "  $name: LIVE — restoring into $container (destructive: DROP + RESTORE $dbs)"
    local tmp out
    tmp="$(mktemp -d)"
    tar -xzf "$src" -C "$tmp"
    if docker cp "$tmp/backups/${bname}" "${container}:/var/lib/clickhouse/backups/"; then
      docker exec "$container" chown -R 101:101 "/var/lib/clickhouse/backups/${bname}" 2>/dev/null || true
      if out="$(docker exec "$container" clickhouse client --query \
           "DROP DATABASE IF EXISTS ${dbs} SYNC; RESTORE DATABASE ${dbs} FROM Disk('backups', '${bname}')" 2>&1)"; then
        docker exec "$container" rm -rf "/var/lib/clickhouse/backups/${bname}" >/dev/null 2>&1 || true
        restore_log "  $name: LIVE restore OK"
        rm -rf "$tmp"
        return 0
      else
        restore_log "  $name: LIVE restore FAILED: $(tail -3 <<<"$out")"
        rm -rf "$tmp"
        return 1
      fi
    else
      rm -rf "$tmp"
      restore_log "  $name: LIVE restore FAILED (docker cp)"
      return 1
    fi
  else
    restore_log "  $name: DRY-RUN — would DROP+RESTORE ${dbs} into $container (re-run with --yes, or --test)"
  fi
}

do_qdrant() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local col="${name#qdrant/}"
  local url="${QDRANT_HOST_URL:-http://localhost:6333}"

  if [[ "$TEST" -eq 1 ]]; then
    restore_log "  $name: TEST — recovering snapshot into disposable qdrant"
    local cname="bktest-qdrant-$$" port=16335 ok=0
    docker rm -f "$cname" >/dev/null 2>&1 || true
    if docker run -d --name "$cname" -p "${port}:6333" \
        -v "$src:/qdrant/snapshots/restore.snapshot:ro" qdrant/qdrant:v1.18.1 >/dev/null; then
      for _ in $(seq 1 30); do
        if curl -sf "http://localhost:${port}/collections" >/dev/null 2>&1; then ok=1; break; fi
        sleep 1
      done
      if [[ "$ok" -eq 1 ]]; then
        local out
        if out="$(curl -s -X PUT "http://localhost:${port}/collections/${col}/snapshots/recover" \
              -H 'Content-Type: application/json' \
              -d '{"location":"file:///qdrant/snapshots/restore.snapshot","priority":"snapshot"}' 2>&1)"; then
          local npts
          npts="$(curl -s "http://localhost:${port}/collections/${col}" | jq -r '.result.points_count // 0' 2>/dev/null || echo '?')"
          restore_log "  $name: TEST OK — $npts points in $col"
          docker rm -f "$cname" >/dev/null 2>&1 || true
          return 0
        else
          restore_log "  $name: TEST FAILED: $out"
        fi
      fi
    fi
    docker rm -f "$cname" >/dev/null 2>&1 || true
    restore_log "  $name: TEST FAILED (container not ready?)"
    return 1
  fi

  if [[ "$YES" -eq 1 ]]; then
    restore_log "  $name: LIVE — recovering snapshot into running qdrant (destructive: replaces collection $col)"
    local tmp snapfile out
    tmp="$(mktemp -d)"
    snapfile="restore-$$-${col}.snapshot"
    cp "$src" "$tmp/${snapfile}"
    if docker cp "$tmp/${snapfile}" "qdrant:/qdrant/snapshots/${snapfile}"; then
      if out="$(curl -s -X PUT "${url}/collections/${col}/snapshots/recover" \
            -H 'Content-Type: application/json' \
            -d "{\"location\":\"file:///qdrant/snapshots/${snapfile}\",\"priority\":\"snapshot\"}" 2>&1)"; then
        local npts
        npts="$(curl -s "${url}/collections/${col}" | jq -r '.result.points_count // 0' 2>/dev/null || echo '?')"
        docker exec qdrant rm -f "/qdrant/snapshots/${snapfile}" >/dev/null 2>&1 || true
        restore_log "  $name: LIVE restore OK — $npts points"
        rm -rf "$tmp"
        return 0
      else
        restore_log "  $name: LIVE restore FAILED: $out"
        rm -rf "$tmp"
        return 1
      fi
    else
      rm -rf "$tmp"
      restore_log "  $name: LIVE restore FAILED (docker cp)"
      return 1
    fi
  else
    restore_log "  $name: DRY-RUN — would recover snapshot into running qdrant (re-run with --yes, or --test)"
  fi
}

do_tar() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  if [[ "$YES" -eq 1 ]]; then
    restore_log "  $name: LIVE — extracting $(basename "$src") in place (paths are absolute)"
    local tmp
    tmp="$(mktemp -d)"
    tar -xzf "$src" -C "$tmp"
    # preview what would change, then apply
    local nchanged=0
    while IFS= read -r f; do
      local live="/${f#"$tmp"/}"
      if [[ ! -f "$live" ]] || ! cmp -s "$tmp/$f" "$live" 2>/dev/null; then
        nchanged=$((nchanged+1))
      fi
    done < <(cd "$tmp" && find . -type f | sed 's|^\./||')
    # apply: extract over the real paths
    tar -xzf "$src" -C /
    rm -rf "$tmp"
    restore_log "  $name: LIVE restore OK ($nchanged file(s) changed)"
  else
    restore_log "  $name: DRY-RUN — contents of $(basename "$src"):"
    tar -tzf "$src" | head -20 | sed 's/^/    /'
    restore_log "  $name: DRY-RUN — (re-run with --yes to extract in place)"
  fi
}

do_mirror() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local target
  target="$(jq -r '.source // empty' <<<"$cfg")"
  if [[ -z "$target" ]]; then
    restore_log "  $name: no target path in config — cannot restore mirror"
    return 1
  fi
  local mirror_src="$HOST_ROOT/mirrors/${name}"
  if [[ ! -d "$mirror_src" ]]; then
    restore_log "  $name: no live mirror at $mirror_src"
    return 1
  fi
  if [[ "$YES" -eq 1 ]]; then
    restore_log "  $name: LIVE — rsync $mirror_src/ → $target/ (additive: backup may exclude content, so we don't delete local extras)"
    if rsync "${RSYNC_FLAGS[@]}" "$mirror_src/" "$target/"; then
      restore_log "  $name: LIVE restore OK"
    else
      restore_log "  $name: LIVE restore FAILED"
      return 1
    fi
  else
    local summary
    summary="$(rsync "${RSYNC_FLAGS[@]}" -n -i "$mirror_src/" "$target/" 2>/dev/null | head -15)"
    restore_log "  $name: DRY-RUN — would rsync live mirror → $target/ (additive, preview):"
    echo "$summary" | sed 's/^/    /'
    restore_log "  $name: DRY-RUN — (re-run with --yes to execute)"
  fi
}

do_copy() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local target container cpath
  target="$(jq -r '.source // empty' <<<"$cfg")"
  container="$(jq -r '.container // empty' <<<"$cfg")"
  cpath="$(jq -r '.container_path // empty' <<<"$cfg")"
  if [[ -z "$target" && -z "$container" ]]; then
    restore_log "  $name: no target path in config — cannot restore"
    return 1
  fi
  if [[ "$YES" -eq 1 ]]; then
    if [[ -n "$container" && -n "$cpath" ]]; then
      restore_log "  $name: LIVE — docker cp $(basename "$src") → ${container}:${cpath}"
      if docker cp "$src" "${container}:${cpath}"; then
        restore_log "  $name: LIVE restore OK (restart the container's service if it caches the file in memory)"
      else
        restore_log "  $name: LIVE restore FAILED (docker cp)"
        return 1
      fi
    else
      restore_log "  $name: LIVE — copying $(basename "$src") → $target"
      mkdir -p "$(dirname "$target")"
      if cp -a "$src" "$target"; then
        restore_log "  $name: LIVE restore OK"
      else
        restore_log "  $name: LIVE restore FAILED"
        return 1
      fi
    fi
  else
    if [[ -n "$container" && -n "$cpath" ]]; then
      restore_log "  $name: DRY-RUN — would docker cp $(basename "$src") → ${container}:${cpath} (re-run with --yes)"
    else
      restore_log "  $name: DRY-RUN — would copy $(basename "$src") → $target (re-run with --yes)"
    fi
  fi
}

do_git() {
  local name="$1" src="$2" entry="$3" cfg="$4"
  local repo
  repo="$(jq -r '.repo // empty' <<<"$cfg")"
  restore_log "  $name: bundle heads:"
  git bundle list-heads "$src" | sed 's/^/    /'
  if [[ "$YES" -eq 1 ]]; then
    if [[ -n "${TARGET_DIR:-}" ]]; then
      restore_log "  $name: cloning bundle → ${TARGET_DIR}/repo"
      git clone "$src" "${TARGET_DIR}/repo" >/dev/null
      restore_log "  $name: OK"
    elif [[ -n "$repo" && -d "$repo" ]]; then
      restore_log "  $name: LIVE — fetching bundle into $repo (non-destructive: fetched to refs/heads/restore-main)"
      if git -C "$repo" fetch "$src" "+refs/heads/main:refs/heads/restore-main" 2>/dev/null; then
        restore_log "  $name: OK — compare with: git -C $repo log --oneline main..restore-main"
      else
        restore_log "  $name: FAILED (fetch)"
        return 1
      fi
    else
      restore_log "  $name: no live repo at $repo — use --target DIR to clone into a fresh location"
      return 1
    fi
  else
    restore_log "  $name: DRY-RUN — (re-run with --yes to fetch into $repo, or --target DIR to clone)"
  fi
}

# ---------------------------------------------------------------------
# restore_item <name>
# ---------------------------------------------------------------------
restore_item() {
  local name="$1"
  local resolved
  if ! resolved="$(resolve_item "$name" "$FROM_RUN")"; then
    restore_log "ITEM $name: RESOLVE FAILED"
    return 1
  fi
  local manifest fpath sha run
  IFS=$'\x1f' read -r manifest fpath sha run <<<"$resolved"
  local entry cfg
  entry="$(item_entry "$manifest" "$name")"
  cfg="$(config_item "$name" || true)"
  local type
  type="$(jq -r '.type // empty' <<<"$entry")"
  local src="$HOST_ROOT/$run/$fpath"
  restore_log "ITEM $name: type=$type run=$run path=$fpath"

  # sha256 verify before touching anything (file items with a recorded sha)
  if [[ -n "$sha" && "$sha" != "-" && -f "$src" ]]; then
    local actual
    actual="$(sha256sum "$src" | cut -d' ' -f1)"
    if [[ "$actual" != "$sha" ]]; then
      restore_log "ITEM $name: SHA256 MISMATCH (expected ${sha:0:16}…, got ${actual:0:16}…) — ABORTING"
      return 1
    fi
    restore_log "ITEM $name: sha256 verified"
  fi

  case "$type" in
    mysql_dump)        do_mysql "$name" "$src" "$entry" "$cfg" ;;
    pg_dump)           do_pg "$name" "$src" "$entry" "$cfg" ;;
    clickhouse_backup) do_clickhouse "$name" "$src" "$entry" "$cfg" ;;
    qdrant_snapshot)   do_qdrant "$name" "$src" "$entry" "$cfg" ;;
    tar)               do_tar "$name" "$src" "$entry" "$cfg" ;;
    mirror)            do_mirror "$name" "$src" "$entry" "$cfg" ;;
    rsync|file)        do_copy "$name" "$src" "$entry" "$cfg" ;;
    git_bundle)        do_git "$name" "$src" "$entry" "$cfg" ;;
    *) restore_log "ITEM $name: no restore method for type '$type'"; return 1 ;;
  esac
}

# ---------------------------------------------------------------------
# item mode
# ---------------------------------------------------------------------
if [[ ${#ITEMS[@]} -gt 0 ]]; then
  local_rc=0
  for name in "${ITEMS[@]}"; do
    restore_item "$name" || local_rc=1
  done
  exit "$local_rc"
fi

# ---------------------------------------------------------------------
# --full
# ---------------------------------------------------------------------
if [[ "$ACTION" == "full" ]]; then
  # Full recovery = the latest good copy of EVERY item. Items may span
  # runs (daily items from the newest daily run, weekly items from the
  # newest weekly run). The item list is the union of:
  #   - config items (daily + weekly), excluding the qdrant umbrella
  #   - every qdrant/<collection> entry seen in any committed manifest
  qcols="$(committed_manifests | while read -r m; do
             jq -r '.items[] | select(.name | startswith("qdrant/")) | .name' "$m" 2>/dev/null
           done | sort -u)"
  cfg_items="$(jq -r '((.daily // []) + (.weekly // []))[] | select(.name != "qdrant") | .name' "$CONFIG" 2>/dev/null | awk '!seen[$0]++')"
  full_items="$( { echo "$cfg_items"; echo "$qcols"; } | grep -v '^$' | awk '!seen[$0]++')"
  if [[ -z "$full_items" ]]; then
    echo "ERROR: no items to restore (empty config / no committed runs)" >&2
    exit 2
  fi

  # ---- staging mode: --target DIR (fresh-disk rebuild path) -------------
  if [[ -n "$TARGET_DIR" ]]; then
    mkdir -p "$TARGET_DIR"
    restore_log "FULL: staging latest copy of every item → $TARGET_DIR"
    mkdir -p "$TARGET_DIR/tars" "$TARGET_DIR/artifacts" "$TARGET_DIR/qdrant" "$TARGET_DIR/mirrors"
    staged=0 skipped=0
    while IFS= read -r name; do
      [[ -z "$name" ]] && continue
      if ! r="$(resolve_item "$name" 2>/dev/null)"; then
        restore_log "  $name: SKIP (no stored copy in any run)"
        skipped=$((skipped+1)); continue
      fi
      IFS=$'\x1f' read -r m fpath sha run <<<"$r"
      # type comes from the config (authoritative); the manifest entry may be
      # absent for live mirrors. qdrant/<col> maps to the config item "qdrant".
      cfgname="$name"
      [[ "$name" == qdrant/* ]] && cfgname="qdrant"
      cfgitem="$(config_item "$cfgname" || true)"
      type="$(jq -r '.type // empty' <<<"$cfgitem")"
      if [[ "$type" == "mirror" ]]; then
        # live mirror — always the freshest, at HOST_ROOT/mirrors/<name>/
        src="$HOST_ROOT/mirrors/$name"
        dest="$TARGET_DIR/mirrors/$name"
        if [[ -d "$src" ]]; then
          mkdir -p "$dest"
          rsync "${RSYNC_FLAGS[@]}" "$src/" "$dest/"
          staged=$((staged+1))
          printf '%s\t%s\t%s\n' "$name" "$type" "mirrors/$name/" >> "$TARGET_DIR/.staged.tsv"
        else
          restore_log "  $name: SKIP (mirror dir missing: $src)"
          skipped=$((skipped+1))
        fi
        continue
      fi
      src="$HOST_ROOT/$run/$fpath"
      case "$type" in
        tar)             dest="$TARGET_DIR/tars" ;;
        qdrant_snapshot) dest="$TARGET_DIR/qdrant" ;;
        *)               dest="$TARGET_DIR/artifacts" ;;
      esac
      if [[ -f "$src" ]]; then
        cp -a "$src" "$dest/"
        staged=$((staged+1))
        printf '%s\t%s\t%s\n' "$name" "$type" "$(basename "$src")" >> "$TARGET_DIR/.staged.tsv"
      elif [[ -d "$src" ]]; then
        # rsync directory items (presenton, open-webui, mem0, n8n)
        dest="$TARGET_DIR/artifacts/$name"
        mkdir -p "$dest"
        cp -a "$src/." "$dest/"
        staged=$((staged+1))
        printf '%s\t%s\t%s\n' "$name" "$type" "artifacts/$name/" >> "$TARGET_DIR/.staged.tsv"
      else
        restore_log "  $name: SKIP (file missing: $src)"
        skipped=$((skipped+1))
      fi
    done <<<"$full_items"
    # live mirrors (always the freshest)
    if [[ -d "$HOST_ROOT/mirrors" ]]; then
      rsync "${RSYNC_FLAGS[@]}" "$HOST_ROOT/mirrors/" "$TARGET_DIR/mirrors/"
    fi
    # RUNBOOK (generated from what was actually staged)
    {
      echo "# Restore runbook — host $HOST_ID"
      echo
      echo "Generated $(date -u +%FT%TZ). Each item is the newest committed copy"
      echo "(may come from different runs: daily vs weekly)."
      echo
      echo "## 1. Fresh disk prep"
      echo "   - install Ubuntu + docker + compose plugin"
      echo "   - clone the repo:  git clone $TARGET_DIR/artifacts/*.bundle /home/chuck/homelab"
      echo "   - place .env:      tar -xzf $TARGET_DIR/tars/env-*.tar.gz -C /   (or copy from the fire-safe)"
      echo
      echo "## 2. Restore data"
      echo "   - mirrors: rsync (CIFS-safe -rt --modify-window=1 --timeout=60) $TARGET_DIR/mirrors/<name>/ → /home/chuck/data/<name>/"
      echo "   - dotfiles: tar -xzf $TARGET_DIR/tars/dotfiles-*.tar.gz -C /"
      echo "   - misc:     tar -xzf $TARGET_DIR/tars/misc-*.tar.gz -C /"
      echo "   - grafana.db: cp $TARGET_DIR/artifacts/grafana.db → /home/chuck/data/grafana/  (needs sudo: file is 472:root)"
      echo
      echo "## 3. Start services, then load databases"
      echo "   cd /home/chuck/homelab && docker compose -f <service>.yml up -d   # per service"
      echo "   - mysql homelab:    gunzip -c $TARGET_DIR/artifacts/homelab-*.sql.gz | mysql -h thor.local -u <user>"
      echo "   - mysql investorhub: gunzip -c $TARGET_DIR/artifacts/investorhub-*.sql.gz | mysql -h thor.local -u <user>"
      echo "   - litellm pg:  gunzip -c $TARGET_DIR/artifacts/litellm-postgres-*.sql.gz | docker exec -i litellm-db psql -U litellm -d postgres"
      echo "   - plausible:   gunzip -c $TARGET_DIR/artifacts/plausible-db-*.sql.gz | docker exec -i plausible-db psql -U plausible -d postgres"
      echo "   - clickhouse:  tar -xzf $TARGET_DIR/artifacts/clickhouse_plausible-*.tar.gz -C /tmp/ch \\"
      echo "                   && docker cp /tmp/ch/backups/* plausible-events-db:/var/lib/clickhouse/backups/ \\"
      echo "                   && docker exec plausible-events-db clickhouse client --query \"RESTORE DATABASE plausible FROM Disk('backups','<dir>')\""
      echo
      echo "## 4. Qdrant"
      echo "   docker compose up -d qdrant, then per collection (snapshots in $TARGET_DIR/qdrant/):"
      echo "   docker cp $TARGET_DIR/qdrant/<col>-*.snapshot qdrant:/qdrant/snapshots/restore.snapshot"
      echo "   curl -X PUT http://localhost:6333/collections/<col>/snapshots/recover -H 'Content-Type: application/json' -d '{\"location\":\"file:///qdrant/snapshots/restore.snapshot\",\"priority\":\"snapshot\"}'"
      echo
      echo "## 5. What was staged"
      echo "   | item | type | file |"
      echo "   |------|------|------|"
      if [[ -f "$TARGET_DIR/.staged.tsv" ]]; then
        while IFS=$'\t' read -r n t f; do echo "   | $n | $t | $f |"; done < "$TARGET_DIR/.staged.tsv"
      fi
      echo
      echo "## 6. Verify"
      echo "   - docker compose ps (all green)"
      echo "   - smoke queries: SELECT 1 per DB; qdrant /collections points_count; KB search works"
      echo "   - check logs for startup errors"
    } > "$TARGET_DIR/RUNBOOK.md"
    rm -f "$TARGET_DIR/.staged.tsv"
    restore_log "FULL: staging complete → $TARGET_DIR ($staged staged, $skipped skipped; see RUNBOOK.md)"
    exit 0
  fi

  # ---- in-place mode (live system) ---------------------------------------
  if [[ "$YES" -ne 1 ]]; then
    echo "In-place full restore is destructive. Re-run with --yes to execute," >&2
    echo "or use --target DIR to stage everything for a fresh disk first." >&2
    exit 2
  fi
  restore_log "FULL: in-place restore of latest copies (destructive)"
  local_rc=0
  # order: env → mirrors → DBs → qdrant → git/others
  while IFS= read -r name; do
    [[ -z "$name" || "$name" == "env" ]] && continue
    case "$name" in qdrant/*) continue ;; esac
    t="$(jq -r --arg n "$name" '((.daily // []) + (.weekly // []))[] | select(.name==$n) | .type' "$CONFIG" 2>/dev/null | head -1)"
    [[ "$t" == "mirror" ]] && { restore_item "$name" || local_rc=1; }
  done <<<"$full_items"
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    t="$(jq -r --arg n "$name" '((.daily // []) + (.weekly // []))[] | select(.name==$n) | .type' "$CONFIG" 2>/dev/null | head -1)"
    [[ "$t" == "mysql_dump" || "$t" == "pg_dump" || "$t" == "clickhouse_backup" ]] && { restore_item "$name" || local_rc=1; }
  done <<<"$full_items"
  while IFS= read -r name; do
    [[ -n "$name" ]] && { restore_item "$name" || local_rc=1; }
  done <<<"$(echo "$full_items" | grep '^qdrant/')"
  while IFS= read -r name; do
    [[ -z "$name" || "$name" == "env" ]] && continue
    case "$name" in qdrant/*) continue ;; esac
    t="$(jq -r --arg n "$name" '((.daily // []) + (.weekly // []))[] | select(.name==$n) | .type' "$CONFIG" 2>/dev/null | head -1)"
    case "$t" in mirror|mysql_dump|pg_dump|clickhouse_backup) continue ;; esac
    restore_item "$name" || local_rc=1
  done <<<"$full_items"
  restore_item env || local_rc=1
  restore_log "FULL: in-place restore done (rc=$local_rc) — run 'docker compose up -d' and verify services"
  exit "$local_rc"
fi

echo "usage: backup-restore.sh --list | --item <name> ... | --full — see --help" >&2
exit 2