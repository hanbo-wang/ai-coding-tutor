#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: create_backup_snapshot.sh [options]

Create a full production snapshot (database, uploads, notebooks).

Options:
  --deploy-path PATH              Deploy directory (default: /opt/ai-coding-tutor)
  --backup-root PATH              Backup root directory (default: /opt/backups/ai-coding-tutor/daily)
  --source NAME                   Snapshot source label (default: manual)
  --deployment-data-mode MODE     Deployment data mode label for manifest (optional)
  --server-ip IPV4                Server IPv4 value for manifest (optional)
  --prune-days DAYS               Remove snapshots older than DAYS (optional)
  -h, --help                      Show this help text
USAGE
}

DEPLOY_PATH="/opt/ai-coding-tutor"
BACKUP_ROOT="/opt/backups/ai-coding-tutor/daily"
SOURCE="manual"
DEPLOYMENT_DATA_MODE=""
SERVER_IPV4=""
PRUNE_DAYS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy-path)
      DEPLOY_PATH="$2"
      shift 2
      ;;
    --backup-root)
      BACKUP_ROOT="$2"
      shift 2
      ;;
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --deployment-data-mode)
      DEPLOYMENT_DATA_MODE="$2"
      shift 2
      ;;
    --server-ip)
      SERVER_IPV4="$2"
      shift 2
      ;;
    --prune-days)
      PRUNE_DAYS="$2"
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

read_env_value() {
  local env_file="$1"
  local key="$2"
  local line
  local value

  line="$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi

  value="${line#*=}"
  value="${value%$'\r'}"
  case "$value" in
    \"*\")
      value="${value#\"}"
      value="${value%\"}"
      ;;
    \'*\')
      value="${value#\'}"
      value="${value%\'}"
      ;;
  esac
  printf '%s' "$value"
}

trim_value() {
  printf '%s' "$1" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

ensure_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Required command is missing: $cmd" >&2
    exit 1
  fi
}

prune_old_snapshots() {
  local backup_root="$1"
  local prune_days="$2"

  find "$backup_root" -mindepth 2 -maxdepth 2 -type d -mtime "+$prune_days" -print0 \
    | while IFS= read -r -d '' old_snapshot; do
        rm -rf "$old_snapshot"
      done
  find "$backup_root" -mindepth 1 -maxdepth 1 -type d -empty -delete
}

ensure_command docker
ensure_command zstd
ensure_command sha256sum
ensure_command tar

COMPOSE_FILE="$DEPLOY_PATH/docker-compose.prod.yml"
ENV_FILE="$DEPLOY_PATH/.env"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

POSTGRES_USER="$(trim_value "$(read_env_value "$ENV_FILE" POSTGRES_USER || true)")"
POSTGRES_DB="$(trim_value "$(read_env_value "$ENV_FILE" POSTGRES_DB || true)")"
WEBSITE_DOMAIN="$(trim_value "$(read_env_value "$ENV_FILE" WEBSITE_DOMAIN || true)")"

if [[ -z "$POSTGRES_USER" || -z "$POSTGRES_DB" ]]; then
  echo "POSTGRES_USER and POSTGRES_DB must be set in $ENV_FILE" >&2
  exit 1
fi
if [[ -z "$WEBSITE_DOMAIN" ]]; then
  WEBSITE_DOMAIN="unknown"
fi

if [[ -z "$SERVER_IPV4" ]]; then
  SERVER_IPV4="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n 1 || true)"
fi
if [[ -z "$SERVER_IPV4" ]]; then
  SERVER_IPV4="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [[ -z "$SERVER_IPV4" ]]; then
  SERVER_IPV4="unknown"
fi

if [[ -n "$PRUNE_DAYS" ]] && ! [[ "$PRUNE_DAYS" =~ ^[0-9]+$ ]]; then
  echo "--prune-days must be a non-negative integer" >&2
  exit 1
fi

SNAPSHOT_DATE="$(date +%Y-%m-%d)"
SNAPSHOT_TIME="$(date +%H%M%S)"
SNAPSHOT_DIR="$BACKUP_ROOT/$SNAPSHOT_DATE/$SNAPSHOT_TIME"

mkdir -p "$BACKUP_ROOT/$SNAPSHOT_DATE"
if [[ -e "$SNAPSHOT_DIR" ]]; then
  echo "Snapshot directory already exists: $SNAPSHOT_DIR" >&2
  echo "Retry in the next second to avoid path collision." >&2
  exit 1
fi
mkdir -p "$SNAPSHOT_DIR"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

compose up -d db >/dev/null

compose exec -T db sh -lc "pg_dump -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Fc --no-owner --no-privileges" \
  | zstd -q -19 -T0 -o "$SNAPSHOT_DIR/db.dump.zst"

compose run --rm --no-deps --entrypoint sh backend -lc "set -eu; mkdir -p /data/uploads; tar -C /data/uploads -cf - ." \
  | zstd -q -19 -T0 -o "$SNAPSHOT_DIR/uploads.tar.zst"

compose run --rm --no-deps --entrypoint sh backend -lc "set -eu; mkdir -p /data/notebooks; tar -C /data/notebooks -cf - ." \
  | zstd -q -19 -T0 -o "$SNAPSHOT_DIR/notebooks.tar.zst"

(
  cd "$SNAPSHOT_DIR"
  sha256sum db.dump.zst uploads.tar.zst notebooks.tar.zst > SHA256SUMS
)

DB_SHA="$(awk '$2 == "db.dump.zst" {print $1}' "$SNAPSHOT_DIR/SHA256SUMS")"
UPLOADS_SHA="$(awk '$2 == "uploads.tar.zst" {print $1}' "$SNAPSHOT_DIR/SHA256SUMS")"
NOTEBOOKS_SHA="$(awk '$2 == "notebooks.tar.zst" {print $1}' "$SNAPSHOT_DIR/SHA256SUMS")"

DB_SIZE="$(stat -c %s "$SNAPSHOT_DIR/db.dump.zst")"
UPLOADS_SIZE="$(stat -c %s "$SNAPSHOT_DIR/uploads.tar.zst")"
NOTEBOOKS_SIZE="$(stat -c %s "$SNAPSHOT_DIR/notebooks.tar.zst")"

CREATED_AT="$(date -Iseconds)"
if [[ -n "$DEPLOYMENT_DATA_MODE" ]]; then
  DEPLOYMENT_DATA_MODE_JSON="\"$DEPLOYMENT_DATA_MODE\""
else
  DEPLOYMENT_DATA_MODE_JSON="null"
fi

cat > "$SNAPSHOT_DIR/manifest.json" <<MANIFEST
{
  "website_domain": "$WEBSITE_DOMAIN",
  "server_ipv4": "$SERVER_IPV4",
  "created_at": "$CREATED_AT",
  "snapshot_date": "$SNAPSHOT_DATE",
  "snapshot_time": "$SNAPSHOT_TIME",
  "snapshot_path": "$SNAPSHOT_DIR",
  "source": "$SOURCE",
  "deployment_data_mode": $DEPLOYMENT_DATA_MODE_JSON,
  "files": {
    "db.dump.zst": {
      "size_bytes": $DB_SIZE,
      "sha256": "$DB_SHA"
    },
    "uploads.tar.zst": {
      "size_bytes": $UPLOADS_SIZE,
      "sha256": "$UPLOADS_SHA"
    },
    "notebooks.tar.zst": {
      "size_bytes": $NOTEBOOKS_SIZE,
      "sha256": "$NOTEBOOKS_SHA"
    }
  }
}
MANIFEST

if [[ -n "$PRUNE_DAYS" ]]; then
  prune_old_snapshots "$BACKUP_ROOT" "$PRUNE_DAYS"
fi

echo "SNAPSHOT_DATE=$SNAPSHOT_DATE"
echo "SNAPSHOT_TIME=$SNAPSHOT_TIME"
echo "SNAPSHOT_DIR=$SNAPSHOT_DIR"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "snapshot_date=$SNAPSHOT_DATE"
    echo "snapshot_time=$SNAPSHOT_TIME"
    echo "snapshot_dir=$SNAPSHOT_DIR"
  } >> "$GITHUB_OUTPUT"
fi
