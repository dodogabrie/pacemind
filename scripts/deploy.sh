#!/usr/bin/env bash
set -euo pipefail

# Production deployment script
# Usage: ./scripts/deploy.sh

echo "Deploying PaceMind..."

cd "$(dirname "$0")/.."

# Build and start services
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml up -d --build

# Wait for backend to be ready
echo "Waiting for backend to start..."
for i in $(seq 1 30); do
  if docker compose exec backend python -c "
from app import create_app
from database import db
app = create_app()
with app.app_context():
    db.session.execute(db.text('SELECT 1'))
    print('ok')
" 2>/dev/null | grep -q ok; then
    break
  fi
  echo "  Attempt $i/30..."
  sleep 2
done

# Pre-migration safety: backup the database
echo "Backing up database before migration..."
BACKUP_FILE="backups/pre_deploy_$(date +%Y%m%d_%H%M%S).sql.gz"
mkdir -p backups
if docker compose exec postgres pg_dump -U trail trail_gpx | gzip > "$BACKUP_FILE" 2>/dev/null; then
  echo "Backup OK: $BACKUP_FILE ($(wc -c < "$BACKUP_FILE") bytes)"
else
  echo "WARNING: backup failed — aborting deployment for safety"
  exit 1
fi

# Run database migrations — DO NOT swallow errors
echo "Running database migrations..."
docker compose exec backend flask db upgrade

echo ""
echo "Deployment complete!"
docker compose ps
echo ""
echo "Backup saved to: $BACKUP_FILE"
echo "To rollback: gunzip -c $BACKUP_FILE | docker compose exec -T postgres psql -U trail trail_gpx"
