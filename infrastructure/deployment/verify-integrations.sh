#!/usr/bin/env bash
set -euo pipefail
umask 077

test_dir=$(mktemp -d)
export RP_HOST_ENV_FILE="$test_dir/.env"
export RP_API_IMAGE=researchpilot-api:local
export RP_FRONTEND_IMAGE=researchpilot-frontend:local
test_origin="https://localhost:${RP_TEST_HTTPS_PORT:-14443}"
python_command=$(command -v python)
if [[ -x .venv/bin/python ]]; then python_command="$PWD/.venv/bin/python"; fi

cat > "$RP_HOST_ENV_FILE" <<ENV
RP_SITE_ADDRESS=https://localhost
RP_ORIGIN=$test_origin
RP_DATABASE_URL=postgresql+psycopg://researchpilot:fixture-only@postgres/researchpilot
RP_REDIS_URL=redis://redis:6379/0
RP_S3_BUCKET=researchpilot-integration
RP_S3_ENDPOINT=http://object-store:5000
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=fixture-only
AWS_SECRET_ACCESS_KEY=fixture-only
NO_PROXY=object-store,scanner,localhost,127.0.0.1
no_proxy=object-store,scanner,localhost,127.0.0.1
ENV

compose=(docker compose --project-name "researchpilot-integration-$$" --env-file "$RP_HOST_ENV_FILE"
    -f infrastructure/deployment/compose.production.yml -f infrastructure/deployment/compose.integration.yml)
cleanup() {
    local code=$?
    if (( code != 0 )); then "${compose[@]}" logs --tail 60 >&2 || true; fi
    "${compose[@]}" down -v
    rm -r -- "$test_dir"
}
trap cleanup EXIT

"${compose[@]}" up -d --wait --wait-timeout 180 postgres redis scanner object-store
"${compose[@]}" run --rm --no-deps api python -c 'from app.storage import settings, s3; s3().create_bucket(Bucket=settings().s3_bucket)'
"${compose[@]}" run --rm --no-deps api python -m app.integration_probe --verify-detection
"${compose[@]}" up -d --wait --wait-timeout 180
"${compose[@]}" exec -T gateway cat /data/caddy/pki/authorities/local/root.crt > "$test_dir/caddy.crt"
(
    cd backend
    SSL_CERT_FILE="$test_dir/caddy.crt" NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
        "$python_command" -m evaluation.http_smoke "$test_origin"
)
"${compose[@]}" exec -T api alembic check
