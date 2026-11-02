#!/bin/bash
set -e

cd ~/mlown/wsn-uav

cp configs/reliability_lowrate_30s.toml configs/reliability_lowrate_001_30s.toml

sed -i \
  -e 's/name = "reliability_lowrate_30s"/name = "reliability_lowrate_001_30s"/g' \
  -e 's/chFailureRate = 0.05/chFailureRate = 0.01/' \
  configs/reliability_lowrate_001_30s.toml

echo "Created configs/reliability_lowrate_001_30s.toml"
grep -nE 'name|chFailureRate|simTime|seeds' configs/reliability_lowrate_001_30s.toml

python3 -m experiments.run_experiment configs/reliability_lowrate_001_30s.toml
