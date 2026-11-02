#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

FILE="simulation/ns3/wsn-uav/ch-app.cc"

echo "========================================"
echo "Discovery fallback implementation"
echo "========================================"

grep -n -A35 -B12 "EnterDiscovery" "$FILE"

echo
echo "========================================"
echo "Window opening and closing implementation"
echo "========================================"

grep -n -A25 -B8 "OpenWindow\|CloseWindow" "$FILE"
