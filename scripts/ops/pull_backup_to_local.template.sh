#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: pull_backup_to_local.sh [options]

Pull backup snapshots from a production server to a local folder.
Windows PowerShell users should run this script through WSL Bash.

This is a safe template. Copy it to:
  scripts/ops/pull_backup_to_local.sh
and set your own defaults before use.

Options:
  --host SSH_TARGET       SSH target (default: root@your-server-ip)
  --remote-root PATH      Remote backup root (default: /opt/backups/your-project/daily)
  --local-root PATH       Local backup root (default: ./backup)
  --date YYYY-MM-DD       Snapshot date to pull (optional)
  --time HHMMSS           Snapshot time to pull (optional)
  --retention-days DAYS   Local retention window (default: 60)
  -h, --help              Show this help text
USAGE
}

HOST="root@your-server-ip"
REMOTE_ROOT="/opt/backups/ai-coding-tutor/daily"
LOCAL_ROOT="./backup"
SNAPSHOT_DATE=""
SNAPSHOT_TIME=""
RETENTION_DAYS="60"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --remote-root)
      REMOTE_ROOT="$2"
      shift 2
      ;;
    --local-root)
      LOCAL_ROOT="$2"
      shift 2
      ;;
    --date)
      SNAPSHOT_DATE="$2"
      shift 2
      ;;
    --time)
      SNAPSHOT_TIME="$2"
      shift 2
      ;;
    --retention-days)
      RETENTION_DAYS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

ensure_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Required command is missing: $cmd" >&2
    exit 1
  fi
}

if [[ -n "$SNAPSHOT_TIME" && -z "$SNAPSHOT_DATE" ]]; then
  echo "--time requires --date" >&2
  exit 1
fi
if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  echo "--retention-days must be a non-negative integer" >&2
  exit 1
fi
if [[ -n "$SNAPSHOT_DATE" ]] && ! [[ "$SNAPSHOT_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "--date must use YYYY-MM-DD" >&2
  exit 1
fi
if [[ -n "$SNAPSHOT_TIME" ]] && ! [[ "$SNAPSHOT_TIME" =~ ^[0-9]{6}$ ]]; then
  echo "--time must use HHMMSS" >&2
  exit 1
fi

if [[ "$HOST" == "root@your-server-ip" ]]; then
  echo "Set --host or update HOST in the local script before use." >&2
  exit 1
fi

ensure_command ssh
ensure_command rsync
ensure_command sha256sum

ssh_run() {
  ssh "$HOST" "$@"
}

resolve_latest_date() {
  ssh_run "set -euo pipefail; root='$REMOTE_ROOT'; [ -d \"\$root\" ] || exit 1; find \"\$root\" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort | tail -n 1"
}

resolve_latest_time_for_date() {
  local date_value="$1"
  ssh_run "set -euo pipefail; root='$REMOTE_ROOT/$date_value'; [ -d \"\$root\" ] || exit 1; find \"\$root\" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort | tail -n 1"
}

if [[ -z "$SNAPSHOT_DATE" ]]; then
  SNAPSHOT_DATE="$(resolve_latest_date)"
fi
if [[ -z "$SNAPSHOT_TIME" ]]; then
  SNAPSHOT_TIME="$(resolve_latest_time_for_date "$SNAPSHOT_DATE")"
fi

if [[ -z "$SNAPSHOT_DATE" || -z "$SNAPSHOT_TIME" ]]; then
  echo "No snapshot was found under $REMOTE_ROOT" >&2
  exit 1
fi

REMOTE_SNAPSHOT_DIR="$REMOTE_ROOT/$SNAPSHOT_DATE/$SNAPSHOT_TIME"
LOCAL_SNAPSHOT_DIR="$LOCAL_ROOT/$SNAPSHOT_DATE/$SNAPSHOT_TIME"

ssh_run "test -d '$REMOTE_SNAPSHOT_DIR'"

mkdir -p "$LOCAL_SNAPSHOT_DIR"

rsync -a --delete "$HOST:$REMOTE_SNAPSHOT_DIR/" "$LOCAL_SNAPSHOT_DIR/"

(
  cd "$LOCAL_SNAPSHOT_DIR"
  sha256sum -c SHA256SUMS
)

find "$LOCAL_ROOT" -mindepth 2 -maxdepth 2 -type d -mtime "+$RETENTION_DAYS" -print0 \
  | while IFS= read -r -d '' old_snapshot; do
      rm -rf "$old_snapshot"
    done
find "$LOCAL_ROOT" -mindepth 1 -maxdepth 1 -type d -empty -delete

echo "Pulled snapshot: $SNAPSHOT_DATE/$SNAPSHOT_TIME"
echo "Local path: $LOCAL_SNAPSHOT_DIR"
