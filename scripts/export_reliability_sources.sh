#!/bin/bash
set -euo pipefail

REPO="$HOME/mlown/wsn-uav"
OUT="$REPO/reliability_sources.zip"
TMP="$REPO/.reliability_sources_tmp"

cd "$REPO"
rm -rf "$TMP"
mkdir -p "$TMP"

# Core simulator and failover lifecycle
for f in \
  simulation/ns3/wsn-uav/world.h \
  simulation/ns3/wsn-uav/world.cc \
  simulation/ns3/wsn-uav/wsn-uav.cc \
  simulation/ns3/wsn-uav/ch-app.h \
  simulation/ns3/wsn-uav/ch-app.cc \
  simulation/ns3/wsn-uav/uav-app.h \
  simulation/ns3/wsn-uav/uav-app.cc \
  simulation/ns3/wsn-uav/protocol.h \
  simulation/ns3/wsn-uav/config.h \
  docs/DESIGN_DECISIONS.md \
  README.md; do
  if [[ -f "$f" ]]; then
    mkdir -p "$TMP/$(dirname "$f")"
    cp "$f" "$TMP/$f"
  fi
done

# Offline topology/election logic, if present
for d in clustering; do
  if [[ -d "$d" ]]; then
    find "$d" -type f \( -name '*.py' -o -name '*.md' \) -print0 | while IFS= read -r -d '' f; do
      mkdir -p "$TMP/$(dirname "$f")"
      cp "$f" "$TMP/$f"
    done
  fi
done

# Team plan and relevant reliability documentation, if present
for f in TEAM_PLAN.md docs/*.md; do
  if [[ -f "$f" ]]; then
    mkdir -p "$TMP/$(dirname "$f")"
    cp "$f" "$TMP/$f"
  fi
done

rm -f "$OUT"
(cd "$TMP" && zip -qr "$OUT" .)
rm -rf "$TMP"
echo "Created: $OUT"
echo "Upload reliability_sources.zip here."
