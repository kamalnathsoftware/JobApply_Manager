#!/usr/bin/env bash
# Usage: scripts_newmig.sh <rev_id> <message>  -- autogenerate against a scratch SQLite DB and tidy.
set -e
cd "$(dirname "$0")/../backend"
export DATABASE_URL=sqlite:////tmp/claude-0/m.db
rm -f /tmp/claude-0/m.db
../.venv/bin/alembic upgrade head >/dev/null 2>&1
../.venv/bin/alembic revision --autogenerate -m "$2" --rev-id "$1" >/dev/null 2>&1
f=$(ls alembic/versions/${1}_*.py)
sed -i "s/sa.text('(CURRENT_TIMESTAMP)')/sa.func.now()/g; /Alembic commands/d" "$f"
rm -f /tmp/claude-0/m.db
echo "$f"
