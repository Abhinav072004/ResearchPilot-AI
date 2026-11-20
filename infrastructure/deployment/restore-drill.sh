#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 backup.dump" >&2
  exit 2
fi
restore_db="researchpilot_restore_$(date +%s)_$$"
docker compose exec -T postgres pg_restore --list < "$1" > /dev/null
docker compose exec -T postgres createdb -U researchpilot "$restore_db"
trap 'docker compose exec -T postgres dropdb -U researchpilot "$restore_db"' EXIT
docker compose exec -T postgres pg_restore --exit-on-error -U researchpilot -d "$restore_db" < "$1"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U researchpilot -d "$restore_db" \
  -c 'SELECT version_num FROM alembic_version' \
  -c 'SELECT count(*) AS restored_projects FROM projects'
