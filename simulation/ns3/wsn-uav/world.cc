#include "world.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace wsnuav
{

namespace
{

std::vector<std::vector<std::string>>
ReadCsv(const std::string& path)
{
    std::ifstream in(path);
    if (!in)
    {
        NS_FATAL_ERROR("Cannot open " << path << " (run clustering/topology.py first)");
    }
    std::vector<std::vector<std::string>> rows;
    std::string line;
    std::getline(in, line); // header
    while (std::getline(in, line))
    {
        if (line.empty())
        {
            continue;
        }
        std::vector<std::string> cols;
        std::stringstream ss(line);
        std::string c;
        while (std::getline(ss, c, ','))
        {
            cols.push_back(c);
        }
        rows.push_back(cols);
    }
    return rows;
}

Role
ParseRole(const std::string& r)
{
    if (r == "primary")
    {
        return Role::PRIMARY;
    }
    if (r == "backup")
    {
        return Role::BACKUP;
    }
    if (r == "member")
    {
        return Role::MEMBER;
    }
    NS_FATAL_ERROR("Unknown role '" << r << "' in nodes.csv");
}

// Censored-aware time at which `count` sensors have died (deaths sorted ascending).
std::pair<double, bool>
TimeOfDeaths(std::vector<double> deaths, size_t count, double horizon)
{
    std::sort(deaths.begin(), deaths.end());
    if (count == 0 || deaths.size() < count)
    {
        return {horizon, true};
    }
    return {deaths[count - 1], false};
}

} // namespace

void
World::LoadTopology(const std::string& dir)
{
    for (const auto& r : ReadCsv(dir + "/nodes.csv"))
    {
        Sensor s;
        s.id = std::stoul(r.at(0));
        s.x = std::stod(r.at(1));
        s.y = std::stod(r.at(2));
        s.cluster = std::stoul(r.at(3));
        s.role = ParseRole(r.at(4));
        NS_ABORT_MSG_IF(s.id != sensors.size(), "nodes.csv must list node ids 0..N-1 in order");
        sensors.push_back(s);
    }
    for (const auto& r : ReadCsv(dir + "/clusters.csv"))
    {
        Cluster c;
        c.id = std::stoul(r.at(0));
        c.meetX = std::stod(r.at(1));
        c.meetY = std::stod(r.at(2));
        c.primary = std::stoul(r.at(3));
        c.backup = std::stol(r.at(4));
        c.size = std::stoul(r.at(5));
        c.tourIndex = std::stoul(r.at(6));
        NS_ABORT_MSG_IF(c.id != clusters.size(), "clusters.csv must list cluster ids 0..K-1 in order");
        clusters.push_back(c);
    }
    tourOrder.assign(clusters.size(), 0);
    for (const auto& c : clusters)
    {
        tourOrder.at(c.tourIndex) = c.id;
    }
}

double
World::Airtime154() const
{
    return 8.0 * (cfg.readingBytes + cfg.overhead154) / cfg.rate154;
}

double
World::SensorEnergyUsed(const Sensor& s, double now) const
{
    double t = s.alive ? now : s.deathTime;
    double e = cfg.sleepPower * t + s.e154Tx + s.e154Rx;
    if (s.role == Role::PRIMARY)
    {
        e += cfg.chListenDuty154 * (cfg.rxPower154 - cfg.sleepPower) * t;
    }
    if (s.wifiEnergy)
    {
        e += s.wifiEnergy->GetTotalEnergyConsumption();
    }
    return e;
}

double
World::Residual(const Sensor& s, double now) const
{
    return cfg.initialEnergy - SensorEnergyUsed(s, now);
}

void
World::OnReading(Sensor& s, bool hopLost)
{
    Cluster& c = clusters[s.cluster];
    Sensor& ch = sensors[c.primary];
    s.generated++;
    c.generated++;

    if (s.id != ch.id)
    {
        // Member transmits one 802.15.4 frame to its CH (analytic cost, no ns-3 lr-wpan).
        s.e154Tx += cfg.txPower154 * Airtime154();
        if (!ch.alive)
        {
            c.lostChDead++;
            return;
        }
        if (hopLost)
        {
            c.lost154++;
            return;
        }
        ch.e154Rx += cfg.rxPower154 * Airtime154();
    }
    else if (!ch.alive)
    {
        c.lostChDead++;
        return;
    }

    if (c.buffer >= cfg.bufferCapacity)
    {
        c.overflow++;
    }
    else
    {
        c.buffer++;
    }
}

void
World::WriteOutputs(double wallSeconds) const
{
    namespace fs = std::filesystem;
    fs::create_directories(cfg.outDir);
    const double T = cfg.simTime;
    const size_t N = sensors.size();
    const size_t K = clusters.size();

    // ---- data
    uint64_t gen = 0, del = 0, ovf = 0, l154 = 0, lchd = 0, sent = 0, buf = 0;
    for (const auto& c : clusters)
    {
        gen += c.generated;
        del += c.delivered;
        ovf += c.overflow;
        l154 += c.lost154;
        lchd += c.lostChDead;
        sent += c.sentWifi;
        buf += c.buffer;
    }
    const uint64_t lostWifi = sent - del; // includes frames in flight at the horizon

    // ---- energy
    double eTotal = 0, eWifi = 0, e154 = 0, eBase = 0, eCh = 0, eMem = 0;
    size_t nCh = 0, nMem = 0;
    std::vector<double> deaths;
    for (const auto& s : sensors)
    {
        double used = SensorEnergyUsed(s, T);
        eTotal += used;
        double w = s.wifiEnergy ? s.wifiEnergy->GetTotalEnergyConsumption() : 0.0;
        eWifi += w;
        double t = s.alive ? T : s.deathTime;
        eBase += cfg.sleepPower * t;
        e154 += used - w - cfg.sleepPower * t;
        if (s.role == Role::PRIMARY)
        {
            eCh += used;
            nCh++;
        }
        else
        {
            eMem += used;
            nMem++;
        }
        if (!s.alive)
        {
            deaths.push_back(s.deathTime);
        }
    }
    std::vector<double> clusterResidual(K, 0.0);
    for (const auto& s : sensors)
    {
        clusterResidual[s.cluster] += std::max(0.0, Residual(s, T));
    }
    double sumR = 0, sumR2 = 0;
    for (size_t k = 0; k < K; ++k)
    {
        double frac = clusterResidual[k] / (cfg.initialEnergy * clusters[k].size);
        sumR += frac;
        sumR2 += frac * frac;
    }
    double jain = sumR2 > 0 ? sumR * sumR / (K * sumR2) : 0.0;

    auto [fnd, fndCensored] = TimeOfDeaths(deaths, 1, T);
    auto xCount = static_cast<size_t>(std::ceil(cfg.lifetimeDeadFraction * N));
    auto [ltx, ltxCensored] = TimeOfDeaths(deaths, xCount, T);

    // ---- UAV (analytic flight/hover energy)
    double eFlight = cfg.flightPower * uavFlightTime;
    double eHover = cfg.hoverPower * uavHoverTime;
    uint32_t nVisits = 0, nContacts = 0, nFailed = 0;
    uint32_t wSched = 0, wOpened = 0, wMet = 0, wMissed = 0;
    uint32_t discoveryContacts = 0;
    double wListen = 0, awake = 0;
    for (const auto& c : clusters)
    {
        nVisits += c.visits;
        nContacts += c.contacts;
        nFailed += c.failedContacts;
        wSched += c.windowsScheduled;
        wOpened += c.windowsOpened;
        wMet += c.windowsMet;
        wMissed += c.windowsMissed;
        discoveryContacts += c.discoveryContacts;
        wListen += c.windowListenTime;
        awake += c.wifiAwakeTime;
    }
    uint32_t wClosed = wMet + wMissed;

    // ---- ETA error of promised arrivals (scheduled mode only)
    // Signed error e = actual - promised arrival. Early arrivals hold (D8) and are harmless;
    // lateness beyond the half-width w is what makes a scheduled window miss.
    double sumAbs = 0, sumSq = 0, sumSigned = 0;
    uint32_t nEta = 0, nLate = 0;
    for (const auto& v : visits)
    {
        if (v.promisedEta >= 0)
        {
            double e = v.arriveTime - v.promisedEta;
            sumAbs += std::abs(e);
            sumSq += e * e;
            sumSigned += e;
            nLate += e > cfg.wakeHalfWidth;
            nEta++;
        }
    }

    std::ofstream j(cfg.outDir + "/metrics.json");
    j << std::setprecision(10);
    auto nan = [](bool ok, double v) {
        std::ostringstream o;
        o << std::setprecision(10);
        if (ok)
        {
            o << v;
        }
        else
        {
            o << "null";
        }
        return o.str();
    };
    j << "{\n"
      << "  \"schema_version\": 1,\n"
      << "  \"run\": {\"seed\": " << cfg.seed << ", \"sim_time_s\": " << T << ", \"wake_mode\": \""
      << cfg.wakeMode << "\", \"routing\": \"" << cfg.routing << "\", \"num_sensors\": " << N
      << ", \"num_clusters\": " << K << ", \"topology_dir\": \"" << cfg.topologyDir
      << "\", \"wall_time_s\": " << wallSeconds << "},\n"
      << "  \"data\": {\"generated\": " << gen << ", \"delivered\": " << del
      << ", \"pdr\": " << nan(gen > 0, double(del) / gen) << ", \"overflow\": " << ovf
      << ", \"overflow_ratio\": " << nan(gen > 0, double(ovf) / gen) << ", \"lost_154\": " << l154
      << ", \"lost_wifi\": " << lostWifi << ", \"lost_ch_dead\": " << lchd
      << ", \"in_buffer_at_end\": " << buf << "},\n"
      << "  \"energy\": {\"sensor_total_J\": " << eTotal << ", \"sensor_mean_J\": " << eTotal / N
      << ", \"primary_ch_mean_J\": " << nan(nCh > 0, eCh / nCh)
      << ", \"non_primary_mean_J\": " << nan(nMem > 0, eMem / nMem) << ", \"wifi_total_J\": " << eWifi
      << ", \"ieee802154_total_J\": " << e154 << ", \"baseline_total_J\": " << eBase
      << ", \"jain_cluster_residual\": " << jain << "},\n"
      << "  \"lifetime\": {\"first_node_death_s\": " << fnd << ", \"first_node_death_censored\": "
      << (fndCensored ? "true" : "false") << ", \"dead_fraction_x\": " << cfg.lifetimeDeadFraction
      << ", \"lifetime_x_s\": " << ltx << ", \"lifetime_x_censored\": " << (ltxCensored ? "true" : "false")
      << ", \"dead_nodes_at_end\": " << deaths.size() << "},\n"
      << "  \"uav\": {\"distance_m\": " << uavDistance << ", \"flight_time_s\": " << uavFlightTime
      << ", \"delay_time_s\": " << uavDelayTime
      << ", \"hover_time_s\": " << uavHoverTime << ", \"flight_energy_J_est\": " << eFlight
      << ", \"hover_energy_J_est\": " << eHover << ", \"visits\": " << nVisits
      << ", \"contacts\": " << nContacts << ", \"failed_contacts\": " << nFailed
      << ", \"bytes_per_uav_joule\": "
      << nan(eFlight + eHover > 0, del * double(cfg.readingBytes) / (eFlight + eHover)) << "},\n"
      << "  \"wake\": {\"windows_scheduled\": " << wSched
<< ", \"windows_opened\": " << wOpened
<< ", \"windows_met\": " << wMet
<< ", \"windows_missed\": " << wMissed
<< ", \"discovery_contacts\": " << discoveryContacts
<< ", \"meeting_success_rate\": "
<< nan(wClosed > 0, double(wMet) / wClosed)
<< ", \"missed_window_fraction\": "
<< nan(wClosed > 0, double(wMissed) / wClosed)
<< ", \"planned_window_width_s\": "
<< nan(cfg.wakeMode == "scheduled", 2 * cfg.wakeHalfWidth)
<< ", \"mean_window_listen_s\": "
<< nan(wClosed > 0, wListen / wClosed)
<< ", \"ch_wifi_awake_fraction\": "
<< awake / (K * T) << "},\n"
      << "  \"eta\": {\"n\": " << nEta << ", \"mean_signed_error_s\": " << nan(nEta > 0, sumSigned / nEta)
      << ", \"mae_s\": " << nan(nEta > 0, sumAbs / nEta)
      << ", \"rmse_s\": " << nan(nEta > 0, std::sqrt(sumSq / std::max(nEta, 1U)))
      << ", \"late_beyond_window_frac\": " << nan(nEta > 0, double(nLate) / std::max(nEta, 1U)) << "}\n"
      << "}\n";

    std::ofstream pc(cfg.outDir + "/per_cluster.csv");
    pc << "cluster_id,size,generated,delivered,overflow,lost_154,lost_wifi,lost_ch_dead,in_buffer,"
      "visits,contacts,failed_contacts,discovery_contacts,"
      "windows_scheduled,windows_opened,windows_met,windows_missed,"
      "wifi_awake_s,residual_fraction\n";
    for (size_t k = 0; k < K; ++k)
    {
        const auto& c = clusters[k];
        pc << c.id << "," << c.size << "," << c.generated << "," << c.delivered << "," << c.overflow
           << "," << c.lost154 << "," << c.sentWifi - c.delivered << "," << c.lostChDead << ","
           << c.buffer << "," << c.visits << "," << c.contacts << "," << c.failedContacts << ","
           << c.discoveryContacts << ","
           << c.windowsScheduled << "," << c.windowsOpened << ","
           << c.windowsMet << "," << c.windowsMissed << ","
           << c.wifiAwakeTime << "," << clusterResidual[k] / (cfg.initialEnergy * c.size) << "\n";
    }

    std::ofstream pn(cfg.outDir + "/per_node.csv");
    pn << "node_id,cluster_id,role,generated,energy_used_J,wifi_J,residual_J,alive,death_time_s\n";
    const char* roleName[] = {"member", "primary", "backup"};
    for (const auto& s : sensors)
    {
        pn << s.id << "," << s.cluster << "," << roleName[static_cast<int>(s.role)] << ","
           << s.generated << "," << SensorEnergyUsed(s, T) << ","
           << (s.wifiEnergy ? s.wifiEnergy->GetTotalEnergyConsumption() : 0.0) << ","
           << Residual(s, T) << "," << s.alive << "," << s.deathTime << "\n";
    }

    std::ofstream pv(cfg.outDir + "/visits.csv");
    pv << "cluster_id,depart_s,arrive_s,contact_s,end_s,leg_distance_m,promised_eta_s,readings\n";
    for (const auto& v : visits)
    {
        pv << v.cluster << "," << v.departTime << "," << v.arriveTime << "," << v.contactTime << ","
           << v.endTime << "," << v.legDistance << "," << v.promisedEta << "," << v.readings << "\n";
    }
}

} // namespace wsnuav
