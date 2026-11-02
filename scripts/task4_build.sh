#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
NS3_ROOT="$HOME/mlown/ns3-workspace/ns-3.47"

cd "$REPO_ROOT"

if [[ ! -x "$NS3_ROOT/ns3" ]]; then
    echo "ERROR: ns-3 wrapper not found at $NS3_ROOT/ns3"
    exit 1
fi

echo "Repository: $REPO_ROOT"
echo "ns-3 root:  $NS3_ROOT"

cd "$NS3_ROOT"

./ns3 build
