#!/usr/bin/env bash
# Runs ON THE SERVER, as root, through SSM: bash deploy/remote-deploy.sh <commit sha>
# Puts the repo at that commit, starts DemoStore's systems, pulls the images of that commit and starts the pilot.
set -euo pipefail
set +x   # the key is read below; nothing in this file may trace it

SHA="${1:?usage: remote-deploy.sh <commit sha>}"
REGION="${AWS_REGION:-us-east-1}"
REPO_URL="https://github.com/termidy/FDE-Bootcamp.git"   # public: no credential
DIR=/opt/demostore
export HOME="${HOME:-/root}" AWS_DEFAULT_REGION="$REGION"

# 1. the repo at the pushed commit (the systems' files are in it)
if [ ! -d "$DIR/.git" ]; then
  git clone "$REPO_URL" "$DIR"
fi
cd "$DIR"
git fetch --prune origin
git cat-file -e "$SHA^{commit}" 2>/dev/null || git fetch origin "$SHA"
git checkout --force --detach "$SHA"
echo "repo at $(git rev-parse HEAD)"

# 2. DemoStore's systems (their own project; a second deploy leaves running ones alone)
SNOW_INCOMING_EVERY=120 docker compose -f sandbox/systems/compose.yaml up -d --wait
# the PostgreSQL container starts twice (init, then the real server): wait for the end of init, then for a connection
for _ in $(seq 1 60); do
  if docker compose -f sandbox/systems/compose.yaml logs ourdb 2>&1 | grep -q "init process complete" \
     && docker compose -f sandbox/systems/compose.yaml exec -T ourdb pg_isready -h 127.0.0.1 -U demostore -d product >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
docker compose -f sandbox/systems/compose.yaml exec -T ourdb pg_isready -h 127.0.0.1 -U demostore -d product

# 3. images of this commit from ECR (the instance role logs in)
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
export APP_IMAGE="$REGISTRY/fde-course/demostore-app:$SHA"
export WIDGET_IMAGE="$REGISTRY/fde-course/demostore-widget:$SHA"
# what runs, for check.sh (names and tags only, no key)
printf 'export SHA=%s\nexport APP_IMAGE=%s\nexport WIDGET_IMAGE=%s\n' "$SHA" "$APP_IMAGE" "$WIDGET_IMAGE" > "$DIR/.deploy.env"

# 4. the Anthropic key: SSM -> a shell variable -> compose passes it by name. Never printed, never in a file.
set +x
ANTHROPIC_API_KEY="$(aws ssm get-parameter --name /fde-course/anthropic-api-key --with-decryption \
  --query Parameter.Value --output text --region "$REGION")"
export ANTHROPIC_API_KEY

COMPOSE=(docker compose -f compose.yaml -f deploy/compose.server.yaml)
"${COMPOSE[@]}" --profile shadow pull chat widget shadow

# 5. the jobs create the tables and fill the store; all are safe to run again
"${COMPOSE[@]}" run --rm jobs python pipeline.py
"${COMPOSE[@]}" run --rm jobs python policy_index.py
"${COMPOSE[@]}" run --rm jobs python retention.py

# 6. the pilot and the shadow worker
"${COMPOSE[@]}" --profile shadow up -d --remove-orphans
unset ANTHROPIC_API_KEY
echo "deployed $SHA"
