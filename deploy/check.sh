#!/usr/bin/env bash
# Runs ON THE SERVER after remote-deploy.sh: one real chat, then the state of the containers. Non-zero = the deploy is red.
set -euo pipefail
set +x
cd /opt/demostore
# shellcheck disable=SC1091
. ./.deploy.env

echo "commit: $SHA"
echo "app image: $APP_IMAGE"
echo "widget image: $WIDGET_IMAGE"

# the containers must be healthy first (the chat answers only then); wait up to 3 minutes
COMPOSE=(docker compose -f compose.yaml -f deploy/compose.server.yaml --profile shadow)
for _ in $(seq 1 36); do
  bad="$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' chat widget shadow | grep -v ' healthy$' || true)"
  [ -z "$bad" ] && break
  sleep 5
done
"${COMPOSE[@]}" ps
if [ -n "$bad" ]; then echo "NOT HEALTHY: $bad"; exit 1; fi

# a policy question: a 200 with a non-empty reply that carries a source link
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT
CODE="$(curl -sS -m 120 -o "$BODY" -w '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"message": "How many days do I have to return an item?", "market": "UK"}' http://localhost:8080/chat)"
echo "chat: HTTP $CODE"
if [ "$CODE" != "200" ]; then cat "$BODY"; exit 1; fi
python3 - "$BODY" <<'PY'
import json, sys
reply = json.load(open(sys.argv[1])).get("reply", "").strip()
print("reply:", reply)
if not reply:
    sys.exit("check failed: empty reply")
if "http" not in reply:
    sys.exit("check failed: no source link in the reply")
PY
echo "check ok"
