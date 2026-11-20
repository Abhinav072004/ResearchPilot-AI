#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DEPLOY_HOST:?Set DEPLOY_HOST in the production GitHub Environment}"
: "${DEPLOY_USER:?Set DEPLOY_USER in the production GitHub Environment}"
: "${DEPLOY_ROOT:?Set DEPLOY_ROOT in the production GitHub Environment}"
: "${DEPLOY_URL:?Set DEPLOY_URL in the production GitHub Environment}"
: "${DEPLOY_SSH_KEY:?Set DEPLOY_SSH_KEY in the production GitHub Environment}"
: "${DEPLOY_KNOWN_HOSTS:?Set DEPLOY_KNOWN_HOSTS in the production GitHub Environment}"
port=${DEPLOY_PORT:-22}
release_id="$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
[[ $DEPLOY_HOST =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]
[[ $DEPLOY_USER =~ ^[A-Za-z0-9_][A-Za-z0-9_-]*$ ]]
[[ $DEPLOY_ROOT =~ ^/[A-Za-z0-9._/-]+$ ]]
[[ $port =~ ^[1-9][0-9]{0,4}$ && $port -le 65535 ]]
[[ $release_id =~ ^[0-9]+-[0-9]+$ ]]
[[ $DEPLOY_URL =~ ^https://[A-Za-z0-9.-]+$ ]]
[[ $API_IMAGE =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]
[[ $FRONTEND_IMAGE =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]

credentials=$(mktemp -d)
trap 'rm -rf -- "$credentials"' EXIT
printf '%s\n' "$DEPLOY_SSH_KEY" > "$credentials/key"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > "$credentials/known_hosts"

ssh_deploy=(ssh -i "$credentials/key" -p "$port" -o BatchMode=yes -o IdentitiesOnly=yes
    -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$credentials/known_hosts"
    "$DEPLOY_USER@$DEPLOY_HOST")
remote_release="$DEPLOY_ROOT/releases/$release_id"
tar -C infrastructure/deployment -cf - compose.production.yml deploy-release.sh |
    "${ssh_deploy[@]}" "umask 077 && mkdir -p '$remote_release' && tar -x -f - -C '$remote_release'"
"${ssh_deploy[@]}" "bash '$remote_release/deploy-release.sh' '$DEPLOY_ROOT' '$release_id' '$DEPLOY_URL' '$API_IMAGE' '$FRONTEND_IMAGE'"
