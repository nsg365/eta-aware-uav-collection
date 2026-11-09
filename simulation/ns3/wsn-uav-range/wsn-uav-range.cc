// Wi-Fi range calibration for the CH<->UAV link (Phase 1).
//
// Same PHY/MAC/channel settings as the main simulation (802.11g ad hoc, constant rate, log-distance
// path loss). One CH/UAV pair per horizontal offset rho; the UAV hovers at altitude H. Pairs are
// spaced far apart so they cannot hear each other. Each CH sends `packets` unicast UDP frames of
// DATA size (MAC retransmissions enabled, as in the simulation); the delivery ratio per rho is
// written to CSV. R_UAV is then the largest rho with delivery >= the chosen threshold.
// --nakagamiM > 0 adds Nakagami-m fading on top of the path loss. The main simulation has no
// fading, so only nakagamiM = 0 describes the simulated link; fading runs show the margin a real
// channel would need (DESIGN_DECISIONS.md, range calibration).
//
// Usage: ./ns3 run "wsn-uav-range --out=range.csv [--maxRho=60 --step=1 --nakagamiM=1 ...]"

#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"

#include <cmath>
#include <fstream>
#include <vector>

using namespace ns3;

namespace
{
std::vector<uint32_t> g_received;

void
Receive(uint32_t pair, Ptr<Socket> socket)
{
    while (socket->Recv())
    {
        g_received[pair]++;
    }
}

void
Send(Ptr<Socket> socket, Address to, uint32_t bytes, uint32_t left, double gap)
{
    if (left == 0)
    {
        return;
    }
    socket->SendTo(Create<Packet>(bytes), 0, to);
    Simulator::Schedule(Seconds(gap), &Send, socket, to, bytes, left - 1, gap);
}
} // namespace

int
main(int argc, char* argv[])
{
    std::string out = "range.csv";
    std::string wifiMode = "ErpOfdmRate6Mbps";
    double txPowerDbm = 16.0;
    double pathLossExponent = 3.0;
    double referenceLossDb = 46.6777;
    double altitude = 30.0;
    double maxRho = 250.0;
    double step = 5.0;
    uint32_t packets = 500;
    uint32_t bytes = 1012; // DATA frame: 30 readings x 32 B + message header
    double gap = 0.005;
    uint32_t seed = 1;
    double nakagamiM = 0; // 0: no fading (as in the main simulation)
    CommandLine cmd(__FILE__);
    cmd.AddValue("out", "Output CSV", out);
    cmd.AddValue("wifiMode", "802.11g constant mode", wifiMode);
    cmd.AddValue("txPowerDbm", "TX power [dBm]", txPowerDbm);
    cmd.AddValue("pathLossExponent", "Log-distance exponent", pathLossExponent);
    cmd.AddValue("referenceLossDb", "Path loss at 1 m [dB]", referenceLossDb);
    cmd.AddValue("uavAltitude", "UAV altitude [m]", altitude);
    cmd.AddValue("maxRho", "Largest horizontal offset [m]", maxRho);
    cmd.AddValue("step", "Offset step [m]", step);
    cmd.AddValue("packets", "Frames per offset", packets);
    cmd.AddValue("bytes", "UDP payload per frame", bytes);
    cmd.AddValue("seed", "ns-3 run number", seed);
    cmd.AddValue("nakagamiM", "Nakagami-m fading parameter (0 = no fading)", nakagamiM);
    cmd.Parse(argc, argv);
    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(seed);

    std::vector<double> rhos;
    for (double r = 0; r <= maxRho + 1e-9; r += step)
    {
        rhos.push_back(r);
    }
    const size_t P = rhos.size();
    g_received.assign(P, 0);

    NodeContainer ch;
    NodeContainer uav;
    ch.Create(P);
    uav.Create(P);
    MobilityHelper mob;
    mob.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mob.Install(ch);
    mob.Install(uav);
    const double spacing = 20000.0; // ~ -150 dBm between pairs: below the noise floor
    for (size_t i = 0; i < P; ++i)
    {
        ch.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(i * spacing, 0, 0));
        uav.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(i * spacing + rhos[i], 0, altitude));
    }

    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue(wifiMode),
                                 "ControlMode", StringValue(wifiMode));
    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
                               "Exponent", DoubleValue(pathLossExponent),
                               "ReferenceLoss", DoubleValue(referenceLossDb));
    if (nakagamiM > 0)
    {
        channel.AddPropagationLoss("ns3::NakagamiPropagationLossModel",
                                   "m0", DoubleValue(nakagamiM),
                                   "m1", DoubleValue(nakagamiM),
                                   "m2", DoubleValue(nakagamiM));
    }
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    phy.Set("TxPowerStart", DoubleValue(txPowerDbm));
    phy.Set("TxPowerEnd", DoubleValue(txPowerDbm));
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");
    NodeContainer all(ch, uav);
    NetDeviceContainer devices = wifi.Install(phy, mac, all);
    wifi.AssignStreams(devices, 0);

    InternetStackHelper internet;
    internet.Install(all);
    Ipv4AddressHelper ipv4;
    ipv4.SetBase("10.1.0.0", "255.255.0.0");
    Ipv4InterfaceContainer ifs = ipv4.Assign(devices);
    NeighborCacheHelper().PopulateNeighborCache();

    for (size_t i = 0; i < P; ++i)
    {
        Ptr<Socket> rx = Socket::CreateSocket(uav.Get(i), UdpSocketFactory::GetTypeId());
        rx->Bind(InetSocketAddress(Ipv4Address::GetAny(), 9001));
        rx->SetRecvCallback(MakeBoundCallback(&Receive, static_cast<uint32_t>(i)));
        Ptr<Socket> tx = Socket::CreateSocket(ch.Get(i), UdpSocketFactory::GetTypeId());
        Address to = InetSocketAddress(ifs.GetAddress(P + i), 9001);
        Simulator::Schedule(Seconds(1.0), &Send, tx, to, bytes, packets, gap);
    }
    Simulator::Stop(Seconds(1.0 + packets * gap + 5.0));
    Simulator::Run();

    std::ofstream f(out);
    f << "rho_m,distance_m,rx_power_dbm,delivery_ratio\n";
    for (size_t i = 0; i < P; ++i)
    {
        double d = std::hypot(rhos[i], altitude);
        double rxDbm = txPowerDbm - referenceLossDb - 10 * pathLossExponent * std::log10(d);
        f << rhos[i] << "," << d << "," << rxDbm << "," << double(g_received[i]) / packets << "\n";
    }
    Simulator::Destroy();
    std::cout << "wsn-uav-range: wrote " << out << std::endl;
    return 0;
}
