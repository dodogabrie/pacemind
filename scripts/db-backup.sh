#!/bin/sh
# On-demand database backup. Writes a gzipped pg_dump to backend/backups/.
# Usage: ./scripts/db-backup.sh [label]
#   label: optional tag appended to filename (e.g. "pre-migration")
set -e

LABEL="${1:-manual}"
BACKUP_DIR="backend/backups"
TS=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/${LABEL}_${TS}.sql.gz"

mkdir -p "$BACKUP_DIR"
# Backups dir may be root-owned from container-side writes; make it writable.
[ -w "$BACKUP_DIR" ] || chmod 0777 "$BACKUP_DIR" 2>/dev/null || sudo chmod 0777 "$BACKUP_DIR"

echo "Backing up database → $FILE"
docker compose exec -T postgres pg_dump -U trail -d trail_gpx | gzip > "$FILE"

SIZE=$(wc -c < "$FILE")
if [ "$SIZE" -lt 1000 ]; then
  echo "ERROR: backup file is suspiciously small ($SIZE bytes) — deleting"
  rm -f "$FILE"
  exit 1
fi

echo "OK: $FILE ($SIZE bytes)"
