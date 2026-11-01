#!/usr/bin/env bash
set -euo pipefail

# Lint Alembic migrations to catch auto-generated garbage.
#
# Detects the common pitfall where `flask db migrate` is run against an empty
# database and generates a migration that recreates ALL tables.
#
# Usage: ./scripts/lint_migration.sh [migration_file]
#   If no file given, checks all uncommitted migration files.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_file() {
  local file="$1"
  local filename=$(basename "$file")
  local errors=0

  echo "Checking $filename..."

  # 1. Count CREATE TABLE statements (skip for initial schema)
  # `grep -c` prints 0 *and* exits 1 when there are no matches, so a
  # `|| echo 0` fallback would append a second 0 and make every later
  # `[ "$create_count" -gt N ]` fail with "integer expression expected"
  # — silently skipping checks 1 and 3 for any migration that creates no
  # tables. Take grep's own count and only default it when grep itself broke.
  create_count=$(grep -c "op.create_table(" "$file" 2>/dev/null || true)
  create_count=${create_count:-0}
  if [ "$create_count" -gt 3 ] && [ "$filename" != "0001_initial_schema.py" ]; then
    echo -e "  ${RED}FAIL${NC}: $create_count CREATE TABLE statements found."
    echo "        This looks like a migration generated against an empty database."
    echo "        Expected: 1-2 new tables per migration, not $create_count."
    echo ""
    echo "  Tables found:"
    grep "op.create_table(" "$file" | sed "s/.*op.create_table('/    - /" | sed "s/',.*//"
    echo ""
    errors=$((errors + 1))
  fi

  # 2. Check for known hub tables that should NEVER appear in a non-initial migration
  if [ "$filename" != "0001_initial_schema.py" ]; then
    for table in "users" "strava_activities" "gpx_files" "predictions"; do
      if grep -q "op.create_table('$table'" "$file" 2>/dev/null; then
        echo -e "  ${RED}FAIL${NC}: Migration creates '$table' table."
        echo "        This table should only exist in 0001_initial_schema.py."
        echo "        Your migration was likely generated against an empty database."
        errors=$((errors + 1))
      fi
    done
  fi

  # 3. Check for idempotent guards on CREATE TABLE
  if [ "$create_count" -gt 0 ]; then
    if ! grep -q "_table_exists\|table_exists\|inspector.get_table_names\|IF NOT EXISTS" "$file" 2>/dev/null; then
      echo -e "  ${YELLOW}WARN${NC}: No idempotent guards found. Add 'if not _table_exists()' checks."
      echo "        See 0001_initial_schema.py for the pattern."
    fi
  fi

  # 4. Check for DROP TABLE in upgrade (dangerous)
  if grep -q "op.drop_table(" "$file" 2>/dev/null; then
    drop_tables=$(grep "op.drop_table(" "$file" | sed "s/.*op.drop_table('//" | sed "s/')//" | tr '\n' ', ')
    echo -e "  ${YELLOW}WARN${NC}: Migration drops tables: $drop_tables"
    echo "        Make sure this is intentional and data has been migrated."
  fi

  if [ "$errors" -eq 0 ]; then
    echo -e "  ${GREEN}OK${NC}"
  fi

  return $errors
}

# Find files to check
if [ $# -gt 0 ]; then
  files=("$@")
else
  # Check uncommitted migration files (new or modified)
  cd "$(dirname "$0")/.."
  mapfile -t files < <(git diff --name-only --diff-filter=AM HEAD -- 'backend/migrations/versions/*.py' 2>/dev/null)
  if [ ${#files[@]} -eq 0 ]; then
    # Also check untracked
    mapfile -t files < <(git ls-files --others --exclude-standard -- 'backend/migrations/versions/*.py' 2>/dev/null)
  fi
  if [ ${#files[@]} -eq 0 ]; then
    echo "No uncommitted migration files found."
    exit 0
  fi
fi

total_errors=0
for f in "${files[@]}"; do
  if check_file "$f"; then
    :
  else
    total_errors=$((total_errors + $?))
  fi
  echo ""
done

if [ "$total_errors" -gt 0 ]; then
  echo -e "${RED}$total_errors error(s) found. Do NOT commit these migrations.${NC}"
  echo ""
  echo "To fix: rewrite the migration to only include your new table(s)."
  echo "See backend/migrations/versions/c21c14348c44_*.py for a correct example."
  exit 1
else
  echo -e "${GREEN}All migrations look clean.${NC}"
fi
