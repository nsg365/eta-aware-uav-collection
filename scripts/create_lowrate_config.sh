#!/bin/bash
set -e

cd ~/mlown/wsn-uav

cp configs/reliability_test.toml configs/reliability_lowrate.toml

sed -i \
  -e 's/name = "reliability_test"/name = "reliability_lowrate"/g' \
  -e 's/chFailureRate = 0.5/chFailureRate = 0.05/' \
  configs/reliability_lowrate.toml

echo "Created configs/reliability_lowrate.toml"
grep -nE 'name|chFailureRate|seeds|simTime' configs/reliability_lowrate.toml
