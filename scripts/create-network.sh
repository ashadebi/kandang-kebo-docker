#!/usr/bin/env bash
set -euo pipefail

NETWORK_NAME="${1:-hosting-public}"
docker network inspect "$NETWORK_NAME" >/dev/null 2>&1 || docker network create "$NETWORK_NAME"
