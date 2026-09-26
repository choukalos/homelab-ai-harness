#!/usr/bin/env bash
# =====================================================================
# backup-lib.sh — shared helpers for backup-nas.sh / backup-restore.sh
# (plan: docs/backup-audit-2026-09-26.md v3)
# =====================================================================
# Not meant to be executed directly. Sourced by the backup/restore
# scripts. Provides: config resolution, NAS root resolution (mount),
# manifest helpers, and restore logging.
#
# Collision rules (plan §3.5): every host writes ONLY under
# <nas-root>/<host_id>/ — manifests are per-run/per-host, there is no
# shared mutable state, and pruning only ever touches the host's own
# subdirectory.
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_DIR="${HOME}/.local/state"
mkdir -p "$STATE_DIR"

# ---------------------------------------------------------------------
# resolve_config [config_file] [host_id]
# Sets: CONFIG, HOST_ID, ENV_FILE (and sources the env file)
# ---------------------------------------------------------------------
resolve_config() {
  local cfg="${1:-}" host="${2:-}"
  if [[ -z "$cfg" ]]; then
    if [[ -n "$host" ]]; then
      cfg="$SCRIPT_DIR/backup-hosts/${host}.json"
    else
      cfg="$SCRIPT_DIR/backup-hosts/$(hostname -s).json"
    fi
  fi
  if [[ ! -f "$cfg" ]]; then
    echo "ERROR: host config not found: $cfg" >&2
    echo "       (create scripts/backup-hosts/<host>.json — see thor.json)" >&2
    exit 2
  fi
  CONFIG="$cfg"
  HOST_ID="$(jq -r '.host_id // empty' "$CONFIG")"
  if [[ -z "$HOST_ID" || ! "$HOST_ID" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "ERROR: invalid host_id '${HOST_ID}' in $CONFIG (must match ^[a-z0-9][a-z0-9-]*$)" >&2
    exit 2
  fi
  ENV_FILE="$(jq -r '.env_file // empty' "$CONFIG")"
  if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
  fi
}

# ---------------------------------------------------------------------
# ensure_nas_root [root_override] [skip_mount]
# Sets: NAS_ROOT (the share root, e.g. /mnt/nas)
# With root_override (local testing): uses that dir, no mount.
# ---------------------------------------------------------------------
ensure_nas_root() {
  local override="${1:-}" skip="${2:-0}"
  if [[ -n "$override" ]]; then
    NAS_ROOT="$override"
    mkdir -p "$NAS_ROOT"
    return 0
  fi
  local mp server share creds uid gid
  mp="$(jq -r '.nas.mountpoint // "/mnt/nas"' "$CONFIG")"
  if mountpoint -q "$mp" 2>/dev/null; then
    NAS_ROOT="$mp"
    return 0
  fi
  if [[ "$skip" == "1" ]]; then
    echo "ERROR: $mp is not mounted and --skip-mount was given." >&2
    exit 2
  fi
  server="$(jq -r '.nas.server' "$CONFIG")"
  share="$(jq -r '.nas.share' "$CONFIG")"
  creds="$(jq -r '.nas.credentials // "~/.smbcredentials"' "$CONFIG")"
  creds="${creds/#\~/$HOME}"
  if [[ ! -f "$creds" ]]; then
    echo "ERROR: SMB credentials file not found: $creds" >&2
    echo "Create it (mode 600) — never commit it:" >&2
    printf '  printf "username=%%s\\npassword=%%s\\n" "<user>" "<pass>" > %s && chmod 600 %s\n' "$creds" "$creds" >&2
    exit 2
  fi
  uid="$(id -u)"; gid="$(id -g)"
  mkdir -p "$mp" 2>/dev/null || true
  if mount -t cifs "//${server}/${share}" "$mp" \
      -o "credentials=${creds},uid=${uid},gid=${gid},file_mode=0600,dir_mode=0700" 2>/dev/null; then
    NAS_ROOT="$mp"
    return 0
  fi
  echo "ERROR: could not mount //${server}/${share} at $mp (probably needs root)." >&2
  echo "Run once (or add to /etc/fstab):" >&2
  echo "  sudo mkdir -p $mp && sudo mount -t cifs //${server}/${share} $mp -o credentials=${creds},uid=${uid},gid=${gid},file_mode=0600,dir_mode=0700" >&2
  exit 2
}

# ---------------------------------------------------------------------
# Manifest helpers. A committed run = <host-root>/<run-id>/manifest.json
# (the manifest is the LAST write of a run — the commit marker). Run
# dir names: daily-<stamp> | weekly-<stamp> | one-off-<label>-<stamp>.
# ---------------------------------------------------------------------

# committed_manifests: newest-first list of manifest.json paths under HOST_ROOT.
# Sorted by run-dir NAME (run ids embed a YYYYMMDD-HHMMSS stamp, so
# lexicographic = chronological for daily/weekly; deterministic for one-off).
committed_manifests() {
  find "$HOST_ROOT" -maxdepth 2 -name manifest.json 2>/dev/null | while read -r m; do
    case "$(basename "$(dirname "$m")")" in
      daily-*|weekly-*|one-off-*)
        # only list manifests with a valid items array (skip corrupt/partial)
        if jq -e '.items | type == "array"' "$m" >/dev/null 2>&1; then
          printf '%s\n' "$m"
        fi
        ;;
    esac
  done | sort -r
}

latest_manifest() { committed_manifests | head -1; }

run_id_of() { basename "$(dirname "$1")"; }

# manifest_for_run <run-id-or-unique-prefix>: echoes manifest path.
# Fails (returns 1) if not found or ambiguous.
manifest_for_run() {
  local pat="$1" matches
  matches="$(find "$HOST_ROOT" -maxdepth 2 -name manifest.json 2>/dev/null | while read -r m; do
      local b; b="$(basename "$(dirname "$m")")"
      case "$b" in
        daily-*|weekly-*|one-off-*) [[ "$b" == "$pat"* ]] && echo "$m" ;;
      esac
    done | sort -r)"
  local n; n=0; [[ -n "$matches" ]] && n="$(wc -l <<<"$matches" | tr -d ' ')"
  if (( n == 0 )); then return 1; fi
  if [[ -z "$pat" ]]; then
    # empty pattern = most recent committed run
    head -1 <<<"$matches"
    return 0
  fi
  if (( n > 1 )); then
    echo "ERROR: run pattern '$pat' is ambiguous:" >&2
    echo "$matches" | sed "s#$HOST_ROOT/##" >&2
    return 1
  fi
  echo "$matches"
}

# item_entry <manifest> <item-name>: echoes the item's JSON entry (or nothing)
item_entry() {
  jq -c --arg n "$2" '.items[] | select(.name==$n)' "$1" 2>/dev/null | head -1
}

# mirror_exists <name>: true if a live mirror dir exists for this host
mirror_exists() { [[ -d "${HOST_ROOT:-}/mirrors/$1" ]]; }

# resolve_item <item-name> [run-pattern]
# Follows the unchanged (same_as) chain to the run that STORED the file.
# Echoes: <manifest_path>\t<relative_path>\t<sha256-or->\t<run_id>
resolve_item() {
  local name="$1" pat="${2:-}" m="" entry="" hops
  if [[ -n "$pat" ]]; then
    m="$(manifest_for_run "$pat")" || return 1
  else
    # newest committed run that mentions this item (or the latest run
    # if it's a live mirror)
    local found=""
    while IFS= read -r m; do
      if [[ -n "$(item_entry "$m" "$name")" ]] || mirror_exists "$name"; then
        found="$m"; break
      fi
    done < <(committed_manifests)
    if [[ -z "$found" ]]; then
      echo "ERROR: item '$name' not found in any committed run under $HOST_ROOT" >&2
      return 1
    fi
    m="$found"
  fi
  hops=0
  while (( hops < 30 )); do
    entry="$(item_entry "$m" "$name")"
    if [[ -z "$entry" ]]; then
      if mirror_exists "$name"; then
        printf '%s\x1fmirrors/%s\x1f-\x1f%s\n' "$m" "$name" "$(run_id_of "$m")"
        return 0
      fi
      echo "ERROR: item '$name' not found in $(run_id_of "$m")" >&2
      return 1
    fi
    local status; status="$(jq -r '.status // empty' <<<"$entry")"
    if [[ "$status" == "stored" || "$status" == "updated" ]]; then
      printf '%s\x1f%s\x1f%s\x1f%s\n' "$m" "$(jq -r '.path' <<<"$entry")" "$(jq -r '.sha256 // empty' <<<"$entry")" "$(run_id_of "$m")"
      return 0
    elif [[ "$status" == "unchanged" ]]; then
      local same; same="$(jq -r '.same_as // empty' <<<"$entry")"
      if [[ -z "$same" ]]; then
        echo "ERROR: unchanged chain broken for item '$name'" >&2
        return 1
      fi
      m="$(manifest_for_run "$same")" || return 1
      hops=$((hops+1))
    else
      echo "ERROR: item '$name' has status '$status' (not restorable)" >&2
      return 1
    fi
  done
  echo "ERROR: unchanged chain too deep for item '$name'" >&2
  return 1
}

# config_item <item-name>: echoes the item definition from the host
# config (daily+weekly lists) — used by the restore scripts for
# per-type parameters (db names, containers, target paths).
config_item() {
  jq -c --arg n "$1" '((.daily // []) + (.weekly // []))[] | select(.name==$n)' "$CONFIG" 2>/dev/null | head -1
}

# ---------------------------------------------------------------------
# write_manifest <dest>
# Builds manifest.json from the entries file. Called by backup-nas.sh
# with these globals set: RUN_ID, HOST_ID, MODE, STARTED, GIT_HEAD,
# FAILURES, ENTRIES.
# ---------------------------------------------------------------------
write_manifest() {
  local dest="$1"
  local ended; ended="$(date -u +%FT%TZ)"
  jq -cn \
    --arg rid "$RUN_ID" --arg host "$HOST_ID" --arg mode "$MODE" \
    --arg started "$STARTED" --arg ended "$ended" \
    --arg gh "${GIT_HEAD:-}" --argjson fails "${FAILURES:-0}" \
    --slurpfile items "$ENTRIES" \
    '{run_id:$rid, host:$host, mode:$mode, started:$started, ended:$ended,
      git_head:(if $gh=="" then null else $gh end),
      failures:$fails, items:$items}' > "${dest}.tmp" && mv "${dest}.tmp" "$dest"
}

# ---------------------------------------------------------------------
# restore_log <msg>: append to local state log + NAS restore-log
# (best effort — a missing NAS must not break a restore).
# ---------------------------------------------------------------------
restore_log() {
  local line
  line="[$(date -u +%FT%TZ)] [$HOST_ID] $*"
  echo "$line" | tee -a "$STATE_DIR/backup-restore.log"
  if [[ -n "${HOST_ROOT:-}" && -d "${HOST_ROOT:-/nonexistent}" ]]; then
    mkdir -p "$HOST_ROOT/restore-log" 2>/dev/null || true
    echo "$line" >> "$HOST_ROOT/restore-log/restore-$(date +%Y%m%d).log" 2>/dev/null || true
  fi
}