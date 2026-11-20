#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$1
release_id=$2
origin=$3
api_image=$4
frontend_image=$5
release="$root/releases/$release_id"
ready_url="$origin/health/ready"

[[ $root == /* && -f "$root/.env" && -f "$release/compose.production.yml" ]]
[[ $release_id =~ ^[0-9]+-[0-9]+$ ]]
[[ $origin =~ ^https://[A-Za-z0-9.-]+$ ]]
[[ $api_image =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]
[[ $frontend_image =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]

exec 9>"$root/.release.lock"
flock -w 180 9
export RP_HOST_ENV_FILE="$root/.env"
printf 'RP_API_IMAGE=%s\nRP_FRONTEND_IMAGE=%s\n' "$api_image" "$frontend_image" > "$release/images.env"

compose() {
    local dir=$1
    shift
    docker compose --project-name researchpilot-production --env-file "$RP_HOST_ENV_FILE" \
        --env-file "$dir/images.env" --file "$dir/compose.production.yml" "$@"
}

previous=""
if [[ -L $root/current ]]; then
    previous=$(readlink -f "$root/current")
fi

compose "$release" config --quiet
compose "$release" pull
compose "$release" up -d --no-build --pull never --wait --wait-timeout 300 scanner
compose "$release" run --rm --no-deps api python -m app.integration_probe --verify-detection

if compose "$release" up -d --no-build --pull never --wait --wait-timeout 240 &&
        curl --proto '=https' -fsS --max-time 10 --retry 5 --retry-connrefused "$ready_url" >/dev/null; then
    ln -s "$release" "$root/.current-$release_id"
    mv -Tf "$root/.current-$release_id" "$root/current"
    printf 'Released %s to %s\n' "$release_id" "$origin"
else
    if [[ -n $previous && $previous != "$release" ]]; then
        echo "Release failed. Restoring the previous images." >&2
        compose "$previous" up -d --no-build --pull never --wait --wait-timeout 240
    else
        compose "$release" stop gateway api worker scheduler
    fi
    exit 1
fi
