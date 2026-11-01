#!/bin/sh
# Prune agent chat conversations whose last activity is older than N days.
# Keeps agent_conversations table bounded in size. Safe to run repeatedly.
#
# Usage: ./scripts/cleanup-agent-conversations.sh [days]
#   days: retention window in days (default: 30)
#
# Crontab example (daily at 03:17 — odd minute to avoid thundering-herd
# with hourly/midnight jobs):
#
#   17 3 * * * cd /srv/gpx_analyzer && ./scripts/cleanup-agent-conversations.sh 30 >> /var/log/pacemind-cleanup.log 2>&1
#
set -e

DAYS="${1:-30}"

case "$DAYS" in
  ''|*[!0-9]*)
    echo "ERROR: days must be a positive integer (got: '$DAYS')" >&2
    exit 2
    ;;
esac

echo "[$(date -Iseconds)] Pruning agent_conversations older than ${DAYS} days..."

docker compose exec -T backend python <<PY
from app import create_app
from repositories import AgentConversationRepository

app = create_app()
with app.app_context():
    repo = AgentConversationRepository()
    deleted = repo.cleanup_older_than(days=${DAYS})
    repo.commit()
    print(f"Removed {deleted} stale conversation(s).")
PY

echo "[$(date -Iseconds)] Cleanup done."
