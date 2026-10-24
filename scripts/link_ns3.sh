#!/usr/bin/env bash
# Symlink the simulation into an ns-3 tree's scratch/ so `./ns3 build wsn-uav` finds it.
# Usage: scripts/link_ns3.sh [NS3_DIR]   (default: $NS3_DIR or ../ns3-workspace/ns-3.47)
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
ns3="${1:-${NS3_DIR:-$repo/../ns3-workspace/ns-3.47}}"
ns3="$(cd "$ns3" && pwd)"
[ -x "$ns3/ns3" ] || { echo "error: $ns3 is not an ns-3 tree (no ./ns3)" >&2; exit 1; }
target="$ns3/scratch/wsn-uav"
if [ -e "$target" ] && [ ! -L "$target" ]; then
  echo "error: $target exists and is not a symlink; refusing to overwrite" >&2; exit 1
fi
ln -sfn "$repo/simulation/ns3/wsn-uav" "$target"
echo "linked $target -> $repo/simulation/ns3/wsn-uav"
