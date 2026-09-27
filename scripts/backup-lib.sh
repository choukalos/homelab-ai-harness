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
# CIFS / macOS-SMB safety (measured on Matrix against Lego, 2026-09-26).
# Lego's stock SMB server is hostile: SMB 2.1 only, idle sessions killed
# in ~18s–3min, no real Unix modes (reports 755 for everything), mtime
# truncated to 100ns. These mitigations are MANDATORY:
#   * rsync -rt (NOT -a): -a's -p/-g/-o fail on CIFS (no real modes) and
#     defeat --link-dest hardlinking. --modify-window=1 absorbs the 100ns
#     mtime truncation. --timeout=60 aborts a stalled transfer (a >3min
#     idle gap kills the session; 60s keeps us safely under that).
#   * mount: vers=2.1 + soft (a hard mount + dead session = unkillable
#     D-state zombies; only a reboot clears that). See backup-setup.sh.
# ---------------------------------------------------------------------
RSYNC_FLAGS=(-rt --modify-window=1 --timeout=60)

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
  # HOST_ID defaults to the hostname (Matrix's proven approach — the per-host
  # NAS subfolder is /etc/hostname). A config host_id overrides it. Hostnames
  # must be stable + match ^[a-z0-9][a-z0-9-]*$ (thor, matrix, ...).
  HOST_ID="$(jq -r '.host_id // empty' "$CONFIG")"
  [[ -n "$HOST_ID" ]] || HOST_ID="$(hostname -s)"
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
# ensure_mounted <mountpoint>
# CIFS-safe mount with bounded self-heal (Matrix's proven approach).
# Lego's SMB server kills idle sessions; a stale kernel mount then blocks
# the next mount until it's lazy-unmounted. All steps are BOUNDED — never
# an unbounded wait that could hang a cron job. Requires the fstab entry
# (vers=2.1,soft,noauto,x-systemd.automount) + a scoped sudoers rule, both
# installed by backup-setup.sh. `sudo -n` = non-interactive (no TTY prompt).
# ---------------------------------------------------------------------
ensure_mounted() {
  local mp="$1"
  # fast path: already mounted and responsive
  if timeout 15 ls "$mp" >/dev/null 2>&1; then return 0; fi
  echo "[$(date '+%F %T')] mount $mp not healthy — attempting self-heal" >&2
  if grep -q " $mp " /proc/mounts 2>/dev/null; then
    echo "  stale entry in /proc/mounts — lazy-unmounting" >&2
    timeout 30 sudo -n umount -l "$mp" >/dev/null 2>&1 || true
    if grep -q " $mp " /proc/mounts 2>/dev/null; then
      echo "FATAL: CIFS state wedged (still in /proc/mounts after umount -l)." >&2
      echo "       A D-state cifsd/umount is unkillable — reboot required: sudo reboot" >&2
      exit 2
    fi
  fi
  echo "  mounting (timeout 600 — covers Lego's post-churn login rate-limit)" >&2
  if ! timeout 600 sudo -n mount "$mp" >/dev/null 2>&1; then
    echo "FATAL: mount $mp failed." >&2
    echo "       First run? install the fstab entry + sudoers rule once (needs sudo):" >&2
    echo "         sudo scripts/backup-setup.sh" >&2
    echo "       (mount.cifs present?  cifs-utils. Lego up?  ping lego.local)" >&2
    exit 2
  fi
  if ! timeout 15 ls "$mp" >/dev/null 2>&1; then
    echo "FATAL: mounted but probe failed after mount — check Lego is up (ping lego.local)" >&2
    exit 2
  fi
  echo "  mount $mp healthy" >&2
}

# ---------------------------------------------------------------------
# require_free_space <dir> <min_free_bytes>
# Refuse to start if the target has less than MIN free (protects Lego's
# disk from an unbounded backup run). Best-effort: df failure is non-fatal
# (we'd rather back up than block on a df quirk).
# ---------------------------------------------------------------------
require_free_space() {
  local dir="$1" min_free="$2"
  local avail
  avail="$(df -P "${dir%/}" 2>/dev/null | awk 'NR==2 {print $4}' | tr -d ' ')" || true
  if [[ -n "$avail" && "$avail" =~ ^[0-9]+$ ]]; then
    if (( avail * 1024 < min_free )); then
      echo "FATAL: only $(( avail * 1024 / 1024 / 1024 )) MB free under $dir (need $(( min_free / 1024 / 1024 )) MB) — aborting to protect the NAS" >&2
      exit 2
    fi
  fi
}

# ---------------------------------------------------------------------
# ensure_nas_root [root_override] [skip_mount]
# Sets: NAS_ROOT (the share root, e.g. /mnt/lego)
# With root_override (local testing): uses that dir, no mount.
# ---------------------------------------------------------------------
ensure_nas_root() {
  local override="${1:-}" skip="${2:-0}"
  if [[ -n "$override" ]]; then
    NAS_ROOT="$override"
    mkdir -p "$NAS_ROOT"
    return 0
  fi
  local mp creds
  mp="$(jq -r '.nas.mountpoint // "/mnt/lego"' "$CONFIG")"
  if [[ "$skip" == "1" ]]; then
    if ! timeout 15 ls "$mp" >/dev/null 2>&1; then
      echo "ERROR: $mp is not mounted and --skip-mount was given." >&2
      exit 2
    fi
    NAS_ROOT="$mp"
    return 0
  fi
  creds="$(jq -r '.nas.credentials // "~/.smbcredentials"' "$CONFIG")"
  creds="${creds/#\~/$HOME}"
  if [[ ! -f "$creds" ]]; then
    echo "ERROR: SMB credentials file not found: $creds" >&2
    echo "Create it (mode 600) — never commit it:" >&2
    printf '  printf "username=%%s\\npassword=%%s\\n" "<user>" "<pass>" > %s && chmod 600 %s\n' "$creds" "$creds" >&2
    exit 2
  fi
  ensure_mounted "$mp"
  NAS_ROOT="$mp"
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