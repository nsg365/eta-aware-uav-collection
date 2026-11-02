#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "===== World output function ====="
grep -n -A240 -B10 "World::WriteOutputs" simulation/ns3/wsn-uav/world.cc

echo
echo "===== All wake/contact counter references ====="
grep -n -A8 -B8 "windowsScheduled\|windowsMet\|windowsMissed\|failedContacts\|contacts" \
    simulation/ns3/wsn-uav/*.cc

echo
echo "===== CH receive and PLAN handling ====="
sed -n '155,215p' simulation/ns3/wsn-uav/ch-app.cc

echo
echo "===== UAV receive handling ====="
sed -n '206,265p' simulation/ns3/wsn-uav/uav-app.cc
cd "$(dirname "$0")/../.."

echo "===== Cluster metric fields ====="
grep -n -A80 -B10 "struct Cluster" simulation/ns3/wsn-uav/world.h

echo
echo "===== World metric output ====="
grep -n -A180 -B10 "World::WriteMetrics" simulation/ns3/wsn-uav/world.cc

echo
echo "===== CH scheduled-window counters ====="
grep -n -A80 -B15 "windowsScheduled\|windowsMet\|windowsMissed" simulation/ns3/wsn-uav/ch-app.cc

echo
echo "===== UAV contact and PLAN handling ====="
grep -n -A80 -B15 "UavApp::Receive" simulation/ns3/wsn-uav/uav-app.cc
