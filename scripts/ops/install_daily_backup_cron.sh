#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: install_daily_backup_cron.sh [options]

Install or update a daily cron job for production backup snapshots.

Options:
  --script-path PATH     Snapshot script path on server (default: /opt/ai-coding-tutor/scripts/ops/create_backup_snapshot.sh)
  --deploy-path PATH     Deploy directory (default: /opt/ai-coding-tutor)
  --backup-root PATH     Backup root directory (default: /opt/backups/ai-coding-tutor/daily)
  --schedule CRON        Cron schedule in server local time (default: 5 2 * * *)
  --prune-days DAYS      Retention in days (default: 14)
  --log-file PATH        Log file path (default: /var/log/ai-coding-tutor-backup.log)
  -h, --help             Show this help text
USAGE
}

SCRIPT_PATH="/opt/ai-coding-tutor/scripts/ops/create_backup_snapshot.sh"
DEPLOY_PATH="/opt/ai-coding-tutor"
BACKUP_ROOT="/opt/backups/ai-coding-tutor/daily"
SCHEDULE="5 2 * * *"
PRUNE_DAYS="14"
LOG_FILE="/var/log/ai-coding-tutor-backup.log"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --script-path)
      SCRIPT_PATH="$2"
      shift 2
      ;;
    --deploy-path)
      DEPLOY_PATH="$2"
      shift 2
      ;;
    --backup-root)
      BACKUP_ROOT="$2"
      shift 2
      ;;
    --schedule)
      SCHEDULE="$2"
      shift 2
      ;;
    --prune-days)
      PRUNE_DAYS="$2"
      shift 2
      ;;
    --log-file)
      LOG_FILE="$2"
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

if [[ ! -x "$SCRIPT_PATH" ]]; then
  echo "Snapshot script is not executable: $SCRIPT_PATH" >&2
  exit 1
fi
if ! [[ "$PRUNE_DAYS" =~ ^[0-9]+$ ]]; then
  echo "--prune-days must be a non-negative integer" >&2
  exit 1
fi

touch "$LOG_FILE"

CRON_COMMAND="/usr/bin/env bash \"$SCRIPT_PATH\" --deploy-path \"$DEPLOY_PATH\" --backup-root \"$BACKUP_ROOT\" --source daily --prune-days \"$PRUNE_DAYS\" >> \"$LOG_FILE\" 2>&1"
CRON_ENTRY="$SCHEDULE $CRON_COMMAND"

EXISTING_CRONTAB="$(mktemp)"
UPDATED_CRONTAB="$(mktemp)"
trap 'rm -f "$EXISTING_CRONTAB" "$UPDATED_CRONTAB"' EXIT

crontab -l > "$EXISTING_CRONTAB" 2>/dev/null || true

grep -vF "$SCRIPT_PATH" "$EXISTING_CRONTAB" > "$UPDATED_CRONTAB" || true
echo "$CRON_ENTRY" >> "$UPDATED_CRONTAB"
crontab "$UPDATED_CRONTAB"

echo "Installed daily backup cron job:"
echo "$CRON_ENTRY"
echo "Verify with: crontab -l | grep -F '$SCRIPT_PATH'"
echo "Log file: $LOG_FILE"
