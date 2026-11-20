#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose --project-name "researchpilot-integration-$$" -f docker-compose.yml
    -f infrastructure/deployment/compose.integration.yml --profile scanner)
cleanup() {
    local code=$?
    if (( code != 0 )); then "${compose[@]}" logs --tail 80 >&2; fi
    "${compose[@]}" down -v
}
trap cleanup EXIT

"${compose[@]}" up -d --wait --wait-timeout 180 object-store scanner
"${compose[@]}" run --rm --no-deps api python -c 'from app.storage import settings, s3; s3().create_bucket(Bucket=settings().s3_bucket)'
"${compose[@]}" run --rm --no-deps api python -m app.integration_probe --verify-detection
