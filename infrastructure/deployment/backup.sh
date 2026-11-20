#!/usr/bin/env bash
set -euo pipefail
umask 077
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 new-backup.dump" >&2
  exit 2
fi
destination=$1
if [ -e "$destination" ]; then
  echo "Backup path already exists" >&2
  exit 2
fi
tmp=$(mktemp "${destination}.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
docker compose exec -T postgres pg_dump -U researchpilot -d researchpilot --format=custom > "$tmp"
docker compose exec -T postgres pg_restore --list < "$tmp" > /dev/null
ln -- "$tmp" "$destination"
sha256sum -- "$destination"
