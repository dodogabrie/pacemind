#!/bin/sh
set -e

export FLASK_APP=app:create_app

# Run migrations only when explicitly requested (e.g. first deploy)
if [ "$RUN_MIGRATIONS" = "1" ] || [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Running database migrations..."

  # Wait for postgres to be truly ready (belt-and-suspenders with depends_on healthcheck)
  echo "Waiting for database..."
  for i in $(seq 1 30); do
    if python -c "
from app import create_app
from database import db
app = create_app()
with app.app_context():
    db.session.execute(db.text('SELECT 1'))
    print('ok')
" 2>/dev/null | grep -q ok; then
      break
    fi
    echo "  Attempt $i/30 — postgres not ready, waiting..."
    sleep 1
  done

  # Count tables — if this fails, SKIP recovery logic (safe default)
  TABLES=$(python -c "
from app import create_app
from database import db
from sqlalchemy import inspect
app = create_app()
with app.app_context():
    print(len(inspect(db.engine).get_table_names()))
" 2>/dev/null) || TABLES=""

  CURRENT=$(flask db current 2>/dev/null | grep -oE '[a-f0-9]+' | head -1 || echo "")
  HEAD=$(flask db heads 2>/dev/null | grep -oE '[a-f0-9]+' | head -1 || echo "")

  echo "Migration state: TABLES=$TABLES CURRENT=$CURRENT HEAD=$HEAD"

  # ── Auto-backup: pg_dump if we have real tables ──
  BACKUP_DIR="/app/backend/backups"
  mkdir -p "$BACKUP_DIR"
  # Ensure host-side scripts (db-backup.sh, db-migrate.sh) can also write here.
  # Container runs as root; bind mount surfaces files as root on the host otherwise.
  chmod 0777 "$BACKUP_DIR" 2>/dev/null || true
  if [ -n "$TABLES" ] && [ "$TABLES" -gt 1 ] 2>/dev/null; then
    BACKUP_FILE="$BACKUP_DIR/auto_$(date +%Y%m%d_%H%M%S).sql.gz"
    echo "Backing up database ($TABLES tables) ..."
    if command -v pg_dump >/dev/null 2>&1; then
      if pg_dump "$DATABASE_URL" | gzip > "$BACKUP_FILE" 2>/dev/null; then
        echo "Backup OK: $BACKUP_FILE ($(wc -c < "$BACKUP_FILE") bytes)"
        # Keep only last 10 backups
        ls -t "$BACKUP_DIR"/auto_*.sql.gz 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
      else
        echo "WARNING: pg_dump failed — continuing without backup"
        rm -f "$BACKUP_FILE" 2>/dev/null || true
      fi
    else
      echo "WARNING: pg_dump not available — skipping backup"
    fi
  fi

  # SAFETY: Only run recovery if we got a real table count.
  # A failed connection returns empty TABLES — we must NOT treat that as "0 tables".
  if [ -n "$TABLES" ]; then
    if [ "$CURRENT" = "$HEAD" ] && [ "$TABLES" -le 1 ] 2>/dev/null; then
      echo "ERROR: DB stamped at head ($HEAD) but only $TABLES tables exist."
      echo "This usually means the schema was wiped but alembic_version survived."
      echo ""
      echo "Refusing to auto-recover — recovery path can cause silent data loss."
      echo "To restore manually:"
      echo "  ls $BACKUP_DIR"
      echo "  gunzip -c $BACKUP_DIR/<backup>.sql.gz | docker compose exec -T postgres psql -U trail -d trail_gpx"
      echo ""
      echo "Or, if you really want a fresh DB, drop alembic_version manually and re-run with RUN_MIGRATIONS=1."
      exit 1
    fi

    # If tables exist but alembic_version is missing (e.g. manual DB setup),
    # stamp at head so upgrade doesn't replay old migrations on existing tables.
    if [ -z "$CURRENT" ] && [ "$TABLES" -gt 1 ] 2>/dev/null; then
      echo "Tables exist but no alembic_version — stamping at head ($HEAD)..."
      flask db stamp head
    fi
  else
    echo "WARNING: Could not count tables — skipping recovery logic, running upgrade only."
  fi

  if ! flask db upgrade; then
    echo "ERROR: flask db upgrade FAILED"
    echo "Database may be in an inconsistent state."
    echo "Check the migration file and database manually."
    echo "Backups are in: $BACKUP_DIR"
    exit 1
  fi
fi

exec "$@"
