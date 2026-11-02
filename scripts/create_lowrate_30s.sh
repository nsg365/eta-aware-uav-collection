#!/bin/bash
set -e

cd ~/mlown/wsn-uav

cp configs/reliability_lowrate.toml configs/reliability_lowrate_30s.toml

sed -i \
  -e 's/name = "reliability_lowrate"/name = "reliability_lowrate_30s"/g' \
  -e 's/simTime = 300.0/simTime = 30.0/' \
  configs/reliability_lowrate_30s.toml

echo "Created configs/reliability_lowrate_30s.toml"
grep -nE 'name|chFailureRate|simTime|seeds' configs/reliability_lowrate_30s.toml

python3 -m experiments.run_experiment configs/reliability_lowrate_30s.toml
