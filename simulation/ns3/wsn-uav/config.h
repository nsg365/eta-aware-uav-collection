// Simulation configuration. Every field is a command-line argument of the same name;
// experiments/run_experiment.py passes the [simulation] table of a TOML config verbatim.
// Units are part of each description and are SI unless stated (s, m, m/s, W, J, A, dBm, dB).
#ifndef WSN_UAV_CONFIG_H
#define WSN_UAV_CONFIG_H

#include "ns3/command-line.h"

#include <string>

namespace wsnuav
{

struct SimConfig
{
    // Run control
    std::string topologyDir = "";
    std::string outDir = "results/run";
    uint32_t seed = 1; // ns-3 run number (RngSeedManager::SetRun)
    double simTime = 7200.0;
    double energyCheckInterval = 1.0;
    double lifetimeDeadFraction = 0.1; // lifetime_x = time until this fraction of sensors is dead

    // Traffic (sensor readings)
    double readingRate = 0.1;      // readings/s per sensor (Poisson)
    uint32_t readingBytes = 32;    // application payload of one reading
    uint32_t bufferCapacity = 2000; // B_max at the CH, readings
    double lossProb154 = 0.0;      // Bernoulli loss on the abstracted 802.15.4 member->CH hop

    // Sensor energy (802.15.4 side is an analytic ledger; see docs/DESIGN_DECISIONS.md D1)
    double initialEnergy = 500.0; // E0 per sensor [J]; scaled down so depletion occurs in-horizon
    double supplyVoltage = 3.0;
    double rate154 = 250e3;        // 802.15.4 PHY bit rate [bit/s]
    uint32_t overhead154 = 17;     // PHY+MAC overhead per frame [bytes]
    double txPower154 = 0.0522;    // radio TX power draw [W]
    double rxPower154 = 0.0564;    // radio RX power draw [W]
    double sleepPower = 60e-6;     // sensor baseline (MCU + radios asleep) [W]
    double chListenDuty154 = 0.01; // fraction of time a CH keeps 802.15.4 RX on for member slots

    // CH Wi-Fi radio energy (ns-3 WifiRadioEnergyModel currents)
    double wifiTxCurrent = 0.19; // [A] ESP32 reference: 802.11g TX at 16 dBm
    double wifiRxCurrent = 0.10;
    double wifiIdleCurrent = 0.10;
    double wifiSleepCurrent = 0.00015;

    // CH<->UAV Wi-Fi link (ns-3 802.11g, ad hoc, constant rate)
    std::string wifiMode = "ErpOfdmRate6Mbps";
    double txPowerDbm = 16.0;
    double pathLossExponent = 3.0;
    double referenceLossDb = 46.6777; // at 1 m, 2.4 GHz
    uint32_t readingsPerFrame = 30;
    double framePacing = 0.003;       // spacing between DATA frames [s]

    // UAV (flight/hover energy is an analytic abstraction, eq. (9))
    double uavAltitude = 30.0;
    double uavSpeed = 10.0;
    double uavSpeedStd = 1.0;  // per-leg speed noise; source of ETA error
    double uavMinSpeed = 2.0;

    // Random extra delay applied independently to each UAV flight leg
    double uavDelayProb = 0.0; // probability of a delay per leg [0, 1]
    double uavDelayMin = 1.0;  // minimum additional delay [s]
    double uavDelayMax = 5.0;  // maximum additional delay [s]

    double flightPower = 150.0; // [W]
    double hoverPower = 170.0;  // [W]
    double beaconInterval = 0.1;
    double contactWait = 12.0;  // max wait for a CH to answer at a meeting point [s]
    double maxHover = 120.0;    // max total hover per visit [s]
    std::string routing = "tour"; // tour (fixed survey/TSP order); more in Phase 2
    double hoverBudget = 3.0;       // timetable hover allowance per stop after lap 0 [s]
    double planSpeedFactor = 0.9;   // timetable plans legs at this fraction of uavSpeed

    // CH wake scheduling
    std::string wakeMode = "scheduled"; // always_on | duty_cycle | scheduled
    double dutyPeriod = 10.0;   // T_b: discovery/duty-cycle period [s]
    double dutyListen = 1.0;    // t_l: listen time per period [s]
    double wakeHalfWidth = 20.0; // fixed half-width w of a scheduled window [s]
    double adaptiveLateMargin = 20.0; // Empirical upper-quantile late-arrival margin [s]
    double etaQuantile = 0.95;   // Empirical lateness percentile (0.80–0.99)
    uint32_t etaMinSamples = 5;  // Minimum samples before adaptive estimation
    // Maximum absolute per-CH clock offset [s]
    double wDrift = 0.0;
    double planTimeout = 0.5;   // CH waits this long after DONE for a PLAN [s]

    // CH reliability and failover (paper Sec. III-F/G)
    double chFailureRate = 0.0;       // random primary failure hazard [1/s]
    double heartbeatInterval = 1.0;   // primary -> backup heartbeat interval [s]
    uint32_t missedHeartbeats = 3;    // m_h: consecutive misses before takeover
    double replicationInterval = 1.0;  // T_rep: backup buffer replication interval [s]
    double retryInterval = 10.0;      // Delta_r: retry spacing [s]
    uint32_t maxMissedRetries = 3;    // M_max: misses before DISCOVERY

    void Register(ns3::CommandLine& cmd)
    {
        cmd.AddValue("topologyDir", "Directory with nodes.csv and clusters.csv (required)", topologyDir);
        cmd.AddValue("outDir", "Output directory for metrics files", outDir);
        cmd.AddValue("seed", "ns-3 run number for all random streams", seed);
        cmd.AddValue("simTime", "Simulated mission horizon [s]", simTime);
        cmd.AddValue("energyCheckInterval", "Period of the node-death check [s]", energyCheckInterval);
        cmd.AddValue("lifetimeDeadFraction", "Dead fraction defining lifetime_x", lifetimeDeadFraction);
        cmd.AddValue("readingRate", "Poisson reading rate per sensor [1/s]", readingRate);
        cmd.AddValue("readingBytes", "Bytes per reading", readingBytes);
        cmd.AddValue("bufferCapacity", "CH buffer capacity B_max [readings]", bufferCapacity);
        cmd.AddValue("lossProb154", "Loss probability of the abstracted 802.15.4 hop", lossProb154);
        cmd.AddValue("initialEnergy", "Initial sensor energy E0 [J]", initialEnergy);
        cmd.AddValue("supplyVoltage", "Sensor supply voltage [V]", supplyVoltage);
        cmd.AddValue("rate154", "802.15.4 bit rate [bit/s]", rate154);
        cmd.AddValue("overhead154", "802.15.4 per-frame overhead [bytes]", overhead154);
        cmd.AddValue("txPower154", "802.15.4 TX power draw [W]", txPower154);
        cmd.AddValue("rxPower154", "802.15.4 RX power draw [W]", rxPower154);
        cmd.AddValue("sleepPower", "Sensor baseline sleep power [W]", sleepPower);
        cmd.AddValue("chListenDuty154", "CH 802.15.4 listen duty cycle", chListenDuty154);
        cmd.AddValue("wifiTxCurrent", "CH Wi-Fi TX current [A]", wifiTxCurrent);
        cmd.AddValue("wifiRxCurrent", "CH Wi-Fi RX current [A]", wifiRxCurrent);
        cmd.AddValue("wifiIdleCurrent", "CH Wi-Fi idle-listen current [A]", wifiIdleCurrent);
        cmd.AddValue("wifiSleepCurrent", "CH Wi-Fi sleep current [A]", wifiSleepCurrent);
        cmd.AddValue("wifiMode", "802.11g constant data/control mode", wifiMode);
        cmd.AddValue("txPowerDbm", "Wi-Fi TX power [dBm]", txPowerDbm);
        cmd.AddValue("pathLossExponent", "Log-distance path-loss exponent n", pathLossExponent);
        cmd.AddValue("referenceLossDb", "Path loss PL0 at 1 m [dB]", referenceLossDb);
        cmd.AddValue("readingsPerFrame", "Readings aggregated per Wi-Fi DATA frame", readingsPerFrame);
        cmd.AddValue("framePacing", "Spacing between DATA frames [s]", framePacing);
        cmd.AddValue("uavAltitude", "UAV altitude H [m]", uavAltitude);
        cmd.AddValue("uavSpeed", "Mean UAV cruise speed [m/s]", uavSpeed);
        cmd.AddValue("uavSpeedStd", "Std-dev of per-leg UAV speed [m/s]", uavSpeedStd);
        cmd.AddValue("uavMinSpeed", "Lower clamp on per-leg UAV speed [m/s]", uavMinSpeed);
        cmd.AddValue("uavDelayProb", "Probability of extra UAV delay per flight leg [0,1]", uavDelayProb);
        cmd.AddValue("uavDelayMin", "Minimum extra UAV delay [s]", uavDelayMin);
        cmd.AddValue("uavDelayMax", "Maximum extra UAV delay [s]", uavDelayMax);
        cmd.AddValue("flightPower", "UAV cruise power [W]", flightPower);
        cmd.AddValue("hoverPower", "UAV hover power [W]", hoverPower);
        cmd.AddValue("beaconInterval", "UAV POLL period while hovering [s]", beaconInterval);
        cmd.AddValue("contactWait", "Max wait for CH contact at a meeting point [s]", contactWait);
        cmd.AddValue("maxHover", "Max hover time per visit [s]", maxHover);
        cmd.AddValue("routing", "UAV routing policy: tour", routing);
        cmd.AddValue("hoverBudget", "Timetable hover allowance per stop after lap 0 [s]", hoverBudget);
        cmd.AddValue("planSpeedFactor", "Timetable planning speed as a fraction of uavSpeed", planSpeedFactor);
        cmd.AddValue("wakeMode", "CH Wi-Fi wake mode: always_on|duty_cycle|scheduled", wakeMode);
        cmd.AddValue("dutyPeriod", "Duty-cycle / discovery period T_b [s]", dutyPeriod);
        cmd.AddValue("dutyListen", "Listen time per duty period t_l [s]", dutyListen);
        cmd.AddValue("wakeHalfWidth", "Fixed scheduled wake-window half-width w [s]", wakeHalfWidth);
        cmd.AddValue("adaptiveLateMargin", "Adaptive late-arrival wake margin [s]", adaptiveLateMargin);
        cmd.AddValue("etaQuantile", "Empirical lateness percentile (0.80–0.99)", etaQuantile);
        cmd.AddValue("etaMinSamples", "Minimum observations for adaptive ETA margin", etaMinSamples);
        cmd.AddValue("wDrift", "Maximum absolute per-CH clock offset [s]", wDrift);
        cmd.AddValue("planTimeout", "CH wait for PLAN after upload [s]", planTimeout);
        cmd.AddValue("chFailureRate", "Primary CH random failure hazard [1/s]", chFailureRate);
        cmd.AddValue("heartbeatInterval", "Primary-to-backup heartbeat interval [s]", heartbeatInterval);
        cmd.AddValue("missedHeartbeats", "Consecutive missed heartbeats before backup takeover m_h", missedHeartbeats);
        cmd.AddValue("replicationInterval", "Backup buffer replication interval T_rep [s]", replicationInterval);
        cmd.AddValue("retryInterval", "Retry spacing Delta_r [s]", retryInterval);
        cmd.AddValue("maxMissedRetries", "Maximum missed retries before DISCOVERY M_max", maxMissedRetries);
    }
};

} // namespace wsnuav

#endif
