#!/usr/bin/env bash
set -euo pipefail

LOGFILE="/tmp/my-service-mgr-dummy-beta.log"

while true; do
  echo "$(date -Is) dummy-beta heartbeat" >> "$LOGFILE"
  sleep 7
done

