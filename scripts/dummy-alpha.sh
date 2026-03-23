#!/usr/bin/env bash
set -euo pipefail

LOGFILE="/tmp/my-service-mgr-dummy-alpha.log"

while true; do
  echo "$(date -Is) dummy-alpha heartbeat" >> "$LOGFILE"
  sleep 5
done

