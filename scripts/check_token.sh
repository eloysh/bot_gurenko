#!/usr/bin/env bash
set -euo pipefail
if [ -z "${1:-}" ]; then
  echo "Usage: ./scripts/check_token.sh <BOT_TOKEN>"
  exit 1
fi
curl -s "https://api.telegram.org/bot$1/getMe" | jq .
