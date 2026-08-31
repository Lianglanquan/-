#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${1:-http://127.0.0.1}"
curl --fail --silent --show-error --max-time 15 "$BASE_URL/health" >/dev/null
curl --fail --silent --show-error --max-time 15 "$BASE_URL/ready" >/dev/null
curl --fail --silent --show-error --max-time 15 "$BASE_URL/" | grep -q '<div id="root"></div>'
echo "healthcheck ok: $BASE_URL"
