#!/bin/bash
set -e

cd ~/mlown/wsn-uav

cp configs/reliability_lowrate_30s.toml configs/reliability_highrate_30s.toml

sed -i \
  -e 's/name = "reliability_lowrate_30s"/name = "reliability_highrate_30s"/g' \
  -e 's/chFailureRate = 0.05/chFailureRate = 0.5/' \
  configs/reliability_highrate_30s.toml

echo "Created configs/reliability_highrate_30s.toml"
grep -nE 'name|chFailureRate|simTime|seeds' configs/reliability_highrate_30s.toml

python3 -m experiments.run_experiment configs/reliability_highrate_30s.toml
