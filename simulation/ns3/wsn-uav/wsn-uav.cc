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

World g_world;
std::vector<Ptr<ExponentialRandomVariable>> g_interArrival;
Ptr<UniformRandomVariable> g_loss154;
std::map<uint32_t, Ptr<ClusterHeadApp>> g_chApp;    // sensor id -> app (primaries)
std::map<uint32_t, Ptr<WifiNetDevice>> g_wifiDev;   // sensor id -> device (primaries, backups)

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
    Simulator::Schedule(Seconds(g_interArrival[id]->GetValue()), &GenerateReading, id);
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
    }
    Simulator::Schedule(Seconds(g_world.cfg.energyCheckInterval), &CheckEnergy);
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
    NS_ABORT_MSG_IF(c.wakeMode == "scheduled" && !policy.CommitsToOrder(),
                    "wakeMode=scheduled needs a routing policy that commits to a visit order "
                    "(see docs/DESIGN_DECISIONS.md D7)");
    NS_ABORT_MSG_IF(c.dutyListen <= 0 || c.dutyListen >= c.dutyPeriod, "need 0 < dutyListen < dutyPeriod");
    NS_ABORT_MSG_IF(c.uavDelayProb < 0.0 || c.uavDelayProb > 1.0,
                    "uavDelayProb must be in [0, 1]");
    NS_ABORT_MSG_IF(c.uavDelayMin < 0.0 || c.uavDelayMax < c.uavDelayMin,
                    "need 0 <= uavDelayMin <= uavDelayMax");
    NS_ABORT_MSG_IF(c.wDrift < 0.0,
                    "wDrift must be non-negative");
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
            auto app = CreateObject<ClusterHeadApp>(&g_world, s.cluster, p, phase->GetValue(), clockDrift->GetValue());
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
    Ptr<NormalRandomVariable> speed = CreateObject<NormalRandomVariable>();
    speed->SetAttribute("Mean", DoubleValue(cfg.uavSpeed));
    speed->SetAttribute("Variance", DoubleValue(cfg.uavSpeedStd * cfg.uavSpeedStd));
    speed->SetStream(STREAM_SPEED);

    Ptr<UniformRandomVariable> uavDelay = CreateObject<UniformRandomVariable>();
    uavDelay->SetStream(STREAM_UAV_DELAY);

    auto uav = CreateObject<UavApp>(&g_world, std::move(policy), speed, uavDelay);
    uavNode->AddApplication(uav);
    uav->SetStartTime(Seconds(0));
    uav->SetStopTime(Seconds(cfg.simTime));

    // ---- Traffic and energy check
    g_loss154 = CreateObject<UniformRandomVariable>();
    g_loss154->SetStream(STREAM_LOSS154);
    for (uint32_t id = 0; id < N; ++id)
    {
        auto rv = CreateObject<ExponentialRandomVariable>();
        rv->SetAttribute("Mean", DoubleValue(1.0 / cfg.readingRate));
        rv->SetStream(STREAM_TRAFFIC + id);
        g_interArrival.push_back(rv);
        Simulator::Schedule(Seconds(rv->GetValue()), &GenerateReading, id);
    }
    Simulator::Schedule(Seconds(cfg.energyCheckInterval), &CheckEnergy);

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
