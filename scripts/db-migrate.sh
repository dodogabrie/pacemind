#!/bin/sh
# Run Alembic migrations explicitly. Takes a pre-migration backup first.
# Usage: ./scripts/db-migrate.sh
set -e

cd "$(dirname "$0")/.."

echo "→ Taking pre-migration backup..."
./scripts/db-backup.sh pre-migration

echo "→ Linting pending migrations..."
if [ -x ./scripts/lint_migration.sh ]; then
  ./scripts/lint_migration.sh || {
    echo "Migration lint failed. Fix the migration or bypass with: docker compose exec backend flask db upgrade"
    exit 1
  }
fi

echo "→ Running flask db upgrade..."
docker compose exec backend flask db upgrade

echo "OK: migrations applied."
