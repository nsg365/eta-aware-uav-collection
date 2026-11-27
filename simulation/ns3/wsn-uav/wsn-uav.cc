// WSN-UAV data muling: core simulation.
//
// What is simulated by ns-3 models:
//   - CH<->UAV link: 802.11g ad hoc (YansWifiPhy, log-distance path loss, constant rate), UDP.
//   - CH Wi-Fi radio energy: BasicEnergySource + WifiRadioEnergyModel, with real PHY sleep.
//   - UAV motion: WaypointMobilityModel.
// What is abstracted (see docs/DESIGN_DECISIONS.md):
//   - Member->CH 802.15.4 hop: analytic per-frame energy and Bernoulli loss (D1).
//   - UAV flight/hover energy: constant power x time (eq. 9).
//
// Usage: ./ns3 run "wsn-uav --topologyDir=<dir> --outDir=<dir> [--key=value ...]"

#include "ch-app.h"
#include "config.h"
#include "routing-policy.h"
#include "uav-app.h"
#include "world.h"

#include "ns3/core-module.h"
#include "ns3/energy-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"
#include "ns3/wifi-radio-energy-model-helper.h"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <map>

using namespace ns3;
using namespace ns3::energy;
using namespace wsnuav;

NS_LOG_COMPONENT_DEFINE("WsnUavMain");

namespace
{

// Stream indices: fixed per purpose so that strategies run with the same seed see identical
// traffic (common random numbers).
constexpr int64_t STREAM_TRAFFIC = 0; // + sensor id
constexpr int64_t STREAM_LOSS154 = 100000;
constexpr int64_t STREAM_SPEED = 100001;
constexpr int64_t STREAM_UAV_DELAY = 100003;
constexpr int64_t STREAM_PHASE = 100002;
constexpr int64_t STREAM_WIFI = 200000;
constexpr int64_t STREAM_CLOCK_DRIFT = 100004;
constexpr int64_t STREAM_CH_FAILURE = 100005;
constexpr int64_t STREAM_BURST = 100006;

World g_world;
std::vector<Ptr<ExponentialRandomVariable>> g_interArrival;
Ptr<UniformRandomVariable> g_loss154;
Ptr<UniformRandomVariable> g_chFailureRv;
std::map<uint32_t, Ptr<ClusterHeadApp>> g_chApp;    // sensor id -> app (primaries)
std::map<uint32_t, Ptr<WifiNetDevice>> g_wifiDev;   // sensor id -> device (primaries, backups)
Ptr<UavApp> g_uavApp;

void
GenerateReading(uint32_t id)
{
    Sensor& s = g_world.sensors[id];
    if (!s.alive)
    {
        return;
    }
    bool lost = g_world.cfg.lossProb154 > 0 && g_loss154->GetValue() < g_world.cfg.lossProb154;
    g_world.OnReading(s, lost);
    // During an event burst the sensor's cluster reads cfg.burstMultiplier times faster.
    double gap = g_interArrival[id]->GetValue();
    if (!g_world.bursts.empty())
    {
        gap /= g_world.TrafficMultiplier(s.cluster, Simulator::Now().GetSeconds());
    }
    Simulator::Schedule(Seconds(gap), &GenerateReading, id);
}

void
CheckEnergy()
{
    double now = Simulator::Now().GetSeconds();
    for (auto& s : g_world.sensors)
    {
        if (!s.alive || g_world.Residual(s, now) > 0)
        {
            continue;
        }
        s.alive = false;
        s.deathTime = now;
        NS_LOG_INFO(now << "s sensor " << s.id << " depleted");
        if (auto it = g_chApp.find(s.id); it != g_chApp.end())
        {
            it->second->OnDeath();
        }
        else if (auto dv = g_wifiDev.find(s.id); dv != g_wifiDev.end())
        {
            dv->second->GetPhy()->SetOffMode();
        }

        // Re-elect a standby if this sensor was assigned as backup
        // and the cluster's primary is still alive.
        for (auto& c : g_world.clusters)
        {
            if (c.backup == static_cast<int32_t>(s.id) &&
                c.primary != s.id &&
                g_world.sensors.at(c.primary).alive)
            {
                const int32_t replacement =
                    g_world.ElectBackup(c.id, now);

                NS_LOG_INFO(
                    now << "s standby sensor " << s.id
                        << " died; replacement backup for cluster "
                        << c.id << " is " << replacement);
            }
        }
    }
    Simulator::Schedule(Seconds(g_world.cfg.energyCheckInterval), &CheckEnergy);
}

void
ReplicateBuffers()
{
    g_world.ReplicateBuffers();

    Simulator::Schedule(
        Seconds(g_world.cfg.replicationInterval),
        &ReplicateBuffers);
}

void
CheckPrimaryHeartbeats()
{
    const double now = Simulator::Now().GetSeconds();

    for (auto& c : g_world.clusters)
    {
        // A detected failure remains latched if takeover fails. Successful takeover
        // re-arms this cluster so a later promoted-primary failure is detectable.
        if (c.primaryFailureDetected)
        {
            continue;
        }

        Sensor& primaryForFailure = g_world.sensors.at(c.primary);

        // Inject primary CH failures according to an exponential hazard rate.
        // Convert the configured rate [1/s] into probability per check interval.
        const double failureProbability =
            1.0 - std::exp(-g_world.cfg.chFailureRate *
                           g_world.cfg.heartbeatInterval);

        if (primaryForFailure.alive &&
            g_world.cfg.chFailureRate > 0.0 &&
            g_chFailureRv->GetValue() < failureProbability)
        {
            primaryForFailure.alive = false;
            primaryForFailure.deathTime = now;

            if (auto app = g_chApp.find(primaryForFailure.id);
                app != g_chApp.end())
            {
                app->second->OnDeath();
            }

            NS_LOG_INFO(
                now << "s random primary failure injected for cluster "
                    << c.id << ", primary sensor " << primaryForFailure.id);
        }

        const Sensor& primary = primaryForFailure;

        if (!primary.alive)
        {
            c.missedHeartbeatCount++;

            if (c.missedHeartbeatCount >= g_world.cfg.missedHeartbeats
    && !c.primaryFailureDetected)
            {
                c.primaryFailureDetected = true;
                c.primaryFailureDetectedTime = now;
                c.primaryFailures++;

                const uint32_t failedPrimaryId = c.primary;

                NS_LOG_INFO(
                    now << "s primary failure detected for cluster "
                        << c.id << ", primary sensor " << failedPrimaryId);

                // Attempt backup promotion.
                if (c.backup >= 0)
                {
                    const uint32_t backupId =
                    static_cast<uint32_t>(c.backup);

                    if (g_world.PromoteBackup(c.id, now))
                    {
                        // Remove the failed primary from the active CH app map.
                        g_chApp.erase(failedPrimaryId);

                        // Retrieve the promoted backup's Wi-Fi device and PHY.
                        Ptr<WifiNetDevice> backupDevice =
                        g_wifiDev.at(backupId);

                        Ptr<WifiPhy> backupPhy =
                            backupDevice->GetPhy();

                        // Create a new CH application for the promoted backup.
                        auto promotedApp = CreateObject<ClusterHeadApp>(
                            &g_world,
                            c.id,
                            backupId,
                            backupPhy,
                            0.0,
                            0.0);

                        // Attach the application to the backup's node.
                        backupDevice->GetNode()->AddApplication(promotedApp);

                        // Start the application immediately at failover time.
                        // Start/stop times are delays from when the app is added, not absolute times.
                        promotedApp->SetStartTime(Seconds(0));
                        promotedApp->SetStopTime(Seconds(g_world.cfg.simTime - now));

                        // Register the promoted backup as the active CH.
                        g_chApp[backupId] = promotedApp;

                        // Synchronize the UAV's active-primary record.
                        g_uavApp->SetActivePrimary(c.id, backupId);

                        // Re-elect a feasible, live standby using the original Eq. (3)
                        // score; all feasible candidates were radio-provisioned at setup.
                        const int32_t replacementBackup = g_world.ElectBackup(c.id, now);
                        c.missedHeartbeatCount = 0;
                        c.primaryFailureDetected = false;

                        NS_LOG_INFO(now << "s replacement backup for cluster " << c.id
                                        << " is " << replacementBackup);

                        NS_LOG_INFO(
                            now << "s backup sensor " << backupId
                                << " promoted to primary for cluster " << c.id);
                    }
                    else
{
    c.failuresBackupDead++;

    NS_LOG_WARN(
     now << "s backup promotion failed for cluster " << c.id
         << " because backup sensor " << backupId << " is dead");
}
            }
            else
{
    c.failuresNoBackup++;

    NS_LOG_WARN(
         now << "s no backup available for cluster " << c.id);
}
        }
        }
        else
        {
            // A living primary is treated as having delivered its heartbeat.
            c.missedHeartbeatCount = 0;
        }
    }

    Simulator::Schedule(
        Seconds(g_world.cfg.heartbeatInterval),
        &CheckPrimaryHeartbeats);
}

Vector
ReadDepot(const std::string& dir)
{
    std::ifstream in(dir + "/depot.csv");
    NS_ABORT_MSG_IF(!in, "Cannot open " << dir << "/depot.csv");
    std::string header;
    double x;
    double y;
    char comma;
    std::getline(in, header);
    in >> x >> comma >> y;
    return Vector(x, y, 0);
}

void
Validate(const SimConfig& c, const RoutingPolicy& policy)
{
    NS_ABORT_MSG_IF(c.topologyDir.empty(), "--topologyDir is required");
    NS_ABORT_MSG_IF(c.wakeMode != "always_on" && c.wakeMode != "duty_cycle" && c.wakeMode != "scheduled",
                    "wakeMode must be always_on, duty_cycle or scheduled");
    NS_ABORT_MSG_IF(c.dutyListen <= 0 || c.dutyListen >= c.dutyPeriod, "need 0 < dutyListen < dutyPeriod");
    NS_ABORT_MSG_IF(c.uavDelayProb < 0.0 || c.uavDelayProb > 1.0,
                    "uavDelayProb must be in [0, 1]");
    NS_ABORT_MSG_IF(c.uavSpeedJitter < 0.0 || c.uavSpeedJitter >= 1.0,
                    "uavSpeedJitter must be in [0, 1)");
    NS_ABORT_MSG_IF(c.uavDelayMin < 0.0 || c.uavDelayMax < c.uavDelayMin,
                    "need 0 <= uavDelayMin <= uavDelayMax");
    NS_ABORT_MSG_IF(c.wDrift < 0.0,
                    "wDrift must be non-negative");

    NS_ABORT_MSG_IF(c.chFailureRate < 0.0,
                    "chFailureRate must be >= 0");

    NS_ABORT_MSG_IF(c.heartbeatInterval <= 0.0,
                    "heartbeatInterval must be > 0");

    NS_ABORT_MSG_IF(c.missedHeartbeats == 0,
                    "missedHeartbeats must be >= 1");

    NS_ABORT_MSG_IF(c.replicationInterval <= 0.0,
                    "replicationInterval must be > 0");

    NS_ABORT_MSG_IF(c.retryInterval <= 0.0,
                    "retryInterval must be > 0");
    NS_ABORT_MSG_IF(c.retryListen <= 0.0 || c.retryListen >= c.retryInterval,
                    "need 0 < retryListen < retryInterval");

    NS_ABORT_MSG_IF(c.maxMissedRetries == 0,
                    "maxMissedRetries must be >= 1");

    if (c.contactWait < c.dutyPeriod + c.dutyListen)
    {
        std::cerr << "warning: contactWait < dutyPeriod + dutyListen; a duty-cycled CH may be "
                     "missed even when the UAV is on time\n";
    }
}

} // namespace

int
main(int argc, char* argv[])
{
    auto wallStart = std::chrono::steady_clock::now();
    SimConfig& cfg = g_world.cfg;
    CommandLine cmd(__FILE__);
    cfg.Register(cmd);
    cmd.Parse(argc, argv);

    auto policy = MakeRoutingPolicy(cfg.routing);
    Validate(cfg, *policy);
    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(cfg.seed);

    g_world.LoadTopology(cfg.topologyDir);
    const size_t N = g_world.sensors.size();
    const size_t K = g_world.clusters.size();
    Vector depot = ReadDepot(cfg.topologyDir);
    depot.z = cfg.uavAltitude;

    // ---- ns-3 nodes: one per Wi-Fi-equipped sensor (primary/backup CH), plus the UAV.
    // Plain members exist only in the World ledger (their radio is not simulated, D1).
    std::vector<uint32_t> wifiSensors;
    for (const auto& s : g_world.sensors)
    {
        if (s.role != Role::MEMBER)
        {
            wifiSensors.push_back(s.id);
        }
    }
    NodeContainer chNodes;
    chNodes.Create(wifiSensors.size());
    Ptr<Node> uavNode = CreateObject<Node>();
    NodeContainer all(chNodes, NodeContainer(uavNode));

    MobilityHelper fixed;
    fixed.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    fixed.Install(chNodes);
    for (size_t i = 0; i < wifiSensors.size(); ++i)
    {
        const Sensor& s = g_world.sensors[wifiSensors[i]];
        chNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(s.x, s.y, 0));
    }
    Ptr<WaypointMobilityModel> uavMob = CreateObject<WaypointMobilityModel>();
    uavNode->AggregateObject(uavMob);
    uavMob->AddWaypoint(Waypoint(Seconds(0), depot));

    // ---- Wi-Fi
    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue(cfg.wifiMode),
                                 "ControlMode", StringValue(cfg.wifiMode));
    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
                               "Exponent", DoubleValue(cfg.pathLossExponent),
                               "ReferenceLoss", DoubleValue(cfg.referenceLossDb));
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    phy.Set("TxPowerStart", DoubleValue(cfg.txPowerDbm));
    phy.Set("TxPowerEnd", DoubleValue(cfg.txPowerDbm));
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");
    NetDeviceContainer devices = wifi.Install(phy, mac, all);
    wifi.AssignStreams(devices, STREAM_WIFI);

    // ---- CH Wi-Fi energy (ns-3). The ns-3 source is deliberately oversized: WifiRadioEnergyModel
    // otherwise schedules its own premature switch to OFF (observed ~700 s with >250 J left, D2).
    // The real budget E0 is enforced by CheckEnergy() on the combined Wi-Fi + 802.15.4 energy.
    // Capacity: never depleted within the horizon, yet capacity / (lowest power) must stay within
    // the int64-nanosecond range of ns3::Time (ns-3 predicts the time to exhaustion per state).
    double minPower = std::min({cfg.wifiSleepCurrent, cfg.wifiIdleCurrent, cfg.wifiRxCurrent}) * cfg.supplyVoltage;
    double ns3Capacity = std::min(1e6, 1e9 * minPower);
    NS_ABORT_MSG_IF(ns3Capacity < 100 * cfg.initialEnergy ||
                        ns3Capacity < 2 * cfg.simTime * cfg.wifiTxCurrent * cfg.supplyVoltage,
                    "ns-3 source capacity too small for initialEnergy/simTime; raise wifiSleepCurrent");
    BasicEnergySourceHelper source;
    source.Set("BasicEnergySourceInitialEnergyJ", DoubleValue(ns3Capacity));
    source.Set("BasicEnergySupplyVoltageV", DoubleValue(cfg.supplyVoltage));
    source.Set("BasicEnergyLowBatteryThreshold", DoubleValue(0.0));
    EnergySourceContainer sources = source.Install(chNodes);
    WifiRadioEnergyModelHelper radio;
    radio.Set("TxCurrentA", DoubleValue(cfg.wifiTxCurrent));
    radio.Set("RxCurrentA", DoubleValue(cfg.wifiRxCurrent));
    radio.Set("IdleCurrentA", DoubleValue(cfg.wifiIdleCurrent));
    radio.Set("CcaBusyCurrentA", DoubleValue(cfg.wifiIdleCurrent));
    radio.Set("SleepCurrentA", DoubleValue(cfg.wifiSleepCurrent));
    NetDeviceContainer chDevices;
    for (size_t i = 0; i < wifiSensors.size(); ++i)
    {
        chDevices.Add(devices.Get(i));
    }
    DeviceEnergyModelContainer energyModels = radio.Install(chDevices, sources);
    for (size_t i = 0; i < wifiSensors.size(); ++i)
    {
        g_world.sensors[wifiSensors[i]].wifiEnergy = energyModels.Get(i);
        g_wifiDev[wifiSensors[i]] = DynamicCast<WifiNetDevice>(devices.Get(i));
    }

    // ---- IP
    InternetStackHelper internet;
    internet.Install(all);
    Ipv4AddressHelper ipv4;
    ipv4.SetBase("10.1.0.0", "255.255.0.0");
    ipv4.Assign(devices);
    NeighborCacheHelper().PopulateNeighborCache(); // no ARP exchanges with sleeping CHs

    // ---- Applications
    Ptr<UniformRandomVariable> phase = CreateObject<UniformRandomVariable>();
    phase->SetAttribute("Max", DoubleValue(cfg.dutyPeriod));
    phase->SetStream(STREAM_PHASE);
    Ptr<UniformRandomVariable> clockDrift = CreateObject<UniformRandomVariable>();
    clockDrift->SetAttribute("Min", DoubleValue(-cfg.wDrift));
    clockDrift->SetAttribute("Max", DoubleValue(cfg.wDrift));
    clockDrift->SetStream(STREAM_CLOCK_DRIFT);
    for (size_t i = 0; i < wifiSensors.size(); ++i)
    {
        const Sensor& s = g_world.sensors[wifiSensors[i]];
        Ptr<WifiPhy> p = g_wifiDev[s.id]->GetPhy();
        if (s.role == Role::PRIMARY)
        {
            auto app = CreateObject<ClusterHeadApp>(
                &g_world, s.cluster, s.id, p, phase->GetValue(), clockDrift->GetValue());
            chNodes.Get(i)->AddApplication(app);
            app->SetStartTime(Seconds(0));
            app->SetStopTime(Seconds(cfg.simTime));
            g_chApp[s.id] = app;
        }
        else
        {
            // Backup CH: Wi-Fi asleep until failover (Phase 1).
            Simulator::Schedule(Seconds(0), &WifiPhy::SetSleepMode, p, false);
        }
    }
    // Ptr<NormalRandomVariable> speed = CreateObject<NormalRandomVariable>();
    // speed->SetAttribute("Mean", DoubleValue(cfg.uavSpeed));
    // speed->SetAttribute("Variance", DoubleValue(cfg.uavSpeedStd * cfg.uavSpeedStd));
    // speed->SetStream(STREAM_SPEED);

    Ptr<RandomVariableStream> speed;

    if (cfg.uavSpeedJitter > 0.0)
    {
        auto uniformSpeed = CreateObject<UniformRandomVariable>();

        uniformSpeed->SetAttribute(
            "Min",
            DoubleValue(cfg.uavSpeed * (1.0 - cfg.uavSpeedJitter)));

        uniformSpeed->SetAttribute(
            "Max",
            DoubleValue(cfg.uavSpeed * (1.0 + cfg.uavSpeedJitter)));

        uniformSpeed->SetStream(STREAM_SPEED);
        speed = uniformSpeed;
    }
    else
    {
        auto normalSpeed = CreateObject<NormalRandomVariable>();

        normalSpeed->SetAttribute("Mean", DoubleValue(cfg.uavSpeed));
        normalSpeed->SetAttribute(
            "Variance",
            DoubleValue(cfg.uavSpeedStd * cfg.uavSpeedStd));

        normalSpeed->SetStream(STREAM_SPEED);
        speed = normalSpeed;
    }

    Ptr<UniformRandomVariable> uavDelay = CreateObject<UniformRandomVariable>();
    uavDelay->SetStream(STREAM_UAV_DELAY);

    g_uavApp = CreateObject<UavApp>(&g_world, std::move(policy), speed, uavDelay);
    uavNode->AddApplication(g_uavApp);
    g_uavApp->SetStartTime(Seconds(0));
    g_uavApp->SetStopTime(Seconds(cfg.simTime));

    // ---- Traffic and energy check
    g_loss154 = CreateObject<UniformRandomVariable>();
    g_loss154->SetStream(STREAM_LOSS154);
    g_chFailureRv = CreateObject<UniformRandomVariable>();
    g_chFailureRv->SetStream(STREAM_CH_FAILURE);
    if (cfg.burstsPerHour > 0.0)
    {
        // Burst schedule, drawn before the run from its own stream so every routing policy with
        // the same seed sees the same bursts.
        auto gapRv = CreateObject<ExponentialRandomVariable>();
        gapRv->SetAttribute("Mean", DoubleValue(3600.0 / cfg.burstsPerHour));
        gapRv->SetStream(STREAM_BURST);
        auto clusterRv = CreateObject<UniformRandomVariable>();
        clusterRv->SetStream(STREAM_BURST + 1);
        for (double t = gapRv->GetValue(); t < cfg.simTime; t += gapRv->GetValue())
        {
            auto k = static_cast<uint32_t>(clusterRv->GetInteger(0, static_cast<uint32_t>(K - 1)));
            g_world.bursts.push_back({k, t, t + cfg.burstDuration});
        }
    }
    for (uint32_t id = 0; id < N; ++id)
    {
        auto rv = CreateObject<ExponentialRandomVariable>();
        rv->SetAttribute("Mean", DoubleValue(1.0 / cfg.readingRate));
        rv->SetStream(STREAM_TRAFFIC + id);
        g_interArrival.push_back(rv);
        Simulator::Schedule(Seconds(rv->GetValue()), &GenerateReading, id);
    }
    Simulator::Schedule(Seconds(cfg.energyCheckInterval), &CheckEnergy);
    Simulator::Schedule(Seconds(cfg.replicationInterval), &ReplicateBuffers);
    Simulator::Schedule(Seconds(cfg.heartbeatInterval), &CheckPrimaryHeartbeats);

    std::cout << "wsn-uav: N=" << N << " K=" << K << " wakeMode=" << cfg.wakeMode
              << " routing=" << cfg.routing << " seed=" << cfg.seed << " simTime=" << cfg.simTime << "s"
              << std::endl;

    // +1 ns so that application StopApplication() events at simTime run (they finalize the
    // awake/hover time accounting) before the simulator halts.
    Simulator::Stop(Seconds(cfg.simTime) + NanoSeconds(1));
    Simulator::Run();

    double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - wallStart).count();
    g_world.WriteOutputs(wall);
    std::cout << "wsn-uav: wrote " << cfg.outDir << "/metrics.json (wall " << wall << " s)" << std::endl;
    Simulator::Destroy();
    return 0;
}
