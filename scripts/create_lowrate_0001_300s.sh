#!/bin/bash
set -e

cd ~/mlown/wsn-uav

cp configs/reliability_test.toml configs/reliability_lowrate_0001_300s.toml

sed -i \
  -e 's/name = "reliability_test"/name = "reliability_lowrate_0001_300s"/g' \
  -e 's/chFailureRate = 0.5/chFailureRate = 0.001/' \
  configs/reliability_lowrate_0001_300s.toml

echo "Created configs/reliability_lowrate_0001_300s.toml"
grep -nE 'name|chFailureRate|simTime|seeds' configs/reliability_lowrate_0001_300s.toml

python3 -m experiments.run_experiment configs/reliability_lowrate_0001_300s.toml
