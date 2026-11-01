#!/bin/bash
# Dev helper: grant premium / reset plan-gen quota for a user (testing only).
#
# Usage:
#   ./scripts/dev-grant-premium.sh                          # premium for most-recent login
#   ./scripts/dev-grant-premium.sh edoardo_gabrielli        # premium for given strava username
#   ./scripts/dev-grant-premium.sh edoardo_gabrielli reset  # reset gen counter only
#   ./scripts/dev-grant-premium.sh '' premium               # default user, premium mode
#
# Requires the postgres container to be running.
set -e

USERNAME="${1:-}"
MODE="${2:-premium}"   # premium | reset

if [ -z "$USERNAME" ]; then
  USER_FILTER="id = (SELECT id FROM users ORDER BY last_login DESC NULLS LAST LIMIT 1)"
else
  USER_FILTER="strava_username = '${USERNAME}'"
fi

case "$MODE" in
  premium)
    SQL="
      INSERT INTO user_subscriptions (user_id, plan, status, expires_at, plan_generations_this_period, started_at)
      SELECT id, 'premium_monthly', 'active', NOW() + INTERVAL '60 days', 0, NOW()
      FROM users WHERE ${USER_FILTER}
      ON CONFLICT (user_id) DO UPDATE
        SET plan = 'premium_monthly',
            status = 'active',
            expires_at = NOW() + INTERVAL '60 days',
            plan_generations_this_period = 0,
            plan_generations_reset_date = NULL;
      SELECT u.id, u.strava_username, s.plan, s.status, s.expires_at, s.plan_generations_this_period
      FROM user_subscriptions s JOIN users u ON u.id = s.user_id
      WHERE u.${USER_FILTER};
    "
    ;;
  reset)
    SQL="
      UPDATE user_subscriptions SET plan_generations_this_period = 0,
                                    plan_generations_reset_date = NULL
      WHERE user_id = (SELECT id FROM users WHERE ${USER_FILTER});
      SELECT u.id, u.strava_username, s.plan, s.status, s.plan_generations_this_period
      FROM user_subscriptions s JOIN users u ON u.id = s.user_id
      WHERE u.${USER_FILTER};
    "
    ;;
  *)
    echo "Unknown mode: $MODE (use 'premium' or 'reset')" >&2
    exit 2
    ;;
esac

docker compose exec -T postgres bash -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 -c \"$SQL\""
