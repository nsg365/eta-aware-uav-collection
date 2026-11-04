#include "world.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <regex>
#include <limits>

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

double
ReadJsonNumber(const std::string& path, const std::string& key)
{
    std::ifstream in(path);
    NS_ABORT_MSG_IF(!in, "Cannot open topology metadata " << path);
    std::stringstream content;
    content << in.rdbuf();
    std::regex pattern("\\\"" + key + "\\\"\\s*:\\s*(-?[0-9]+(\\.[0-9]+)?)");
    std::smatch match;
    std::string text = content.str();
    NS_ABORT_MSG_IF(!std::regex_search(text, match, pattern), "Missing numeric topology parameter " << key);
    return std::stod(match[1].str());
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

    // Reconstruct Eq. (2) feasible CH candidates from topology geometry and meta.json.
    // This retains candidates beyond the initially elected primary/backup.
    const double sensorRange = ReadJsonNumber(dir + "/meta.json", "sensor_range_m");
    const double uavRange = ReadJsonNumber(dir + "/meta.json", "uav_range_m");
    uavRangeM = uavRange;
    electionAlpha = ReadJsonNumber(dir + "/meta.json", "alpha");
    for (auto& c : clusters)
    {
        std::vector<uint32_t> members;
        for (const auto& sensor : sensors)
            if (sensor.cluster == c.id) members.push_back(sensor.id);
        for (uint32_t candidate : members)
        {
            const Sensor& cand = sensors.at(candidate);
            const double dMeet = std::hypot(cand.x - c.meetX, cand.y - c.meetY);
            if (dMeet > uavRange) continue;
            double maxMemberDistance = 0.0;
            for (uint32_t member : members)
            {
                const Sensor& m = sensors.at(member);
                maxMemberDistance = std::max(maxMemberDistance, std::hypot(cand.x - m.x, cand.y - m.y));
            }
            if (maxMemberDistance <= sensorRange) c.feasibleCandidates.push_back(candidate);
        }
        NS_ABORT_MSG_IF(c.feasibleCandidates.empty(), "Cluster " << c.id << " has no feasible CH candidates");
        // Provision Wi-Fi-capable standby radios for every feasible candidate so that
        // a later re-election can promote one without rebuilding the ns-3 network.
        for (uint32_t id : c.feasibleCandidates)
            if (id != c.primary) sensors.at(id).role = Role::BACKUP;
    }
}

double
World::Airtime154() const
{
    return 8.0 * (cfg.readingBytes + cfg.overhead154) / cfg.rate154;
}

void
World::ReplicateBuffers()
{
    for (auto& c : clusters)
    {
        if (c.backup < 0)
        {
            continue;
        }

        const Sensor& primary = sensors.at(c.primary);
        const Sensor& backup = sensors.at(static_cast<uint32_t>(c.backup));

        if (!primary.alive || !backup.alive)
        {
            continue;
        }

        c.backupBuffer = c.buffer;
    }
}

bool
World::PromoteBackup(uint32_t clusterId, double now)
{
    Cluster& c = clusters.at(clusterId);

    // A cluster without a backup cannot fail over.
    if (c.backup < 0)
    {
        return false;
    }

    Sensor& oldPrimary = sensors.at(c.primary);
    Sensor& backup = sensors.at(static_cast<uint32_t>(c.backup));

    // Promotion is possible only if the backup is still alive.
    if (!backup.alive)
    {
        return false;
    }

    // Recover as much of the primary's failure-time buffer as the
    // backup's replicated copy contains.
    uint64_t recovered =
        std::min(c.backupBuffer, c.bufferLostAtFailure);

    c.lostChDead -= recovered;
    c.lostDuringFailover = c.bufferLostAtFailure - recovered;

    // Change cluster and sensor roles.
    oldPrimary.role = Role::MEMBER;
    backup.role = Role::PRIMARY;
    c.primary = backup.id;

    // Restore the backup's replicated data.
    c.buffer = std::min<uint64_t>(c.backupBuffer, cfg.bufferCapacity);

    // Record failover statistics.
    c.backupPromotions++;
    c.lastFailoverTime = now;

    // This cluster has consumed its backup.
    c.backup = -1;
    c.backupBuffer = 0;
    c.bufferLostAtFailure = 0;

    return true;
}

int32_t
World::ElectBackup(uint32_t clusterId, double now)
{
    Cluster& c = clusters.at(clusterId);
    c.backup = -1;
    c.backupBuffer = 0;
    double bestScore = -std::numeric_limits<double>::infinity();

    for (uint32_t id : c.feasibleCandidates)
    {
        const Sensor& candidate = sensors.at(id);

        if (id == c.primary)
        {
            continue;
        }

        if (!candidate.alive)
        {
            continue;
        }

        if (!candidate.wifiEnergy)
        {
            continue;
        }

        const double distance =
            std::hypot(candidate.x - c.meetX, candidate.y - c.meetY);

        const double energyScore =
            std::clamp(Residual(candidate, now) / cfg.initialEnergy, 0.0, 1.0);

        const double score =
            electionAlpha * energyScore +
            (1.0 - electionAlpha) * (1.0 - distance / uavRangeM);

        if (score > bestScore)
        {
            bestScore = score;
            c.backup = static_cast<int32_t>(id);
        }
    }

    if (c.backup >= 0) sensors.at(static_cast<uint32_t>(c.backup)).role = Role::BACKUP;
    return c.backup;
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
    
    uint64_t totalPrimaryFailures = 0;
    uint64_t totalBackupPromotions = 0;
    uint64_t totalFailuresNoBackup = 0;
    uint64_t totalFailuresBackupDead = 0;

    uint64_t totalRetryAttempts = 0;
    uint64_t totalRetrySuccesses = 0;
    uint64_t totalPromiseViolations = 0;
    uint64_t totalRetryExhaustions = 0;
    uint64_t totalRebootstrapCount = 0;

    uint64_t totalLostDuringFailover = 0;
    double latestFailoverTime = -1.0;

for (const auto& c : clusters)
{
    totalPrimaryFailures += c.primaryFailures;
    totalBackupPromotions += c.backupPromotions;
    totalFailuresNoBackup += c.failuresNoBackup;
    totalFailuresBackupDead += c.failuresBackupDead;

    totalRetryAttempts += c.retryAttempts;
    totalRetrySuccesses += c.retrySuccesses;
    totalPromiseViolations += c.promiseViolations;
    totalRetryExhaustions += c.retryExhaustions;
    totalRebootstrapCount += c.rebootstrapCount;

    totalLostDuringFailover += c.lostDuringFailover;

    if (c.lastFailoverTime >= 0.0)
    {
        latestFailoverTime = std::max(latestFailoverTime, c.lastFailoverTime);
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
      << "  \"reliability\": {\"primary_failures\": " << totalPrimaryFailures
      << ", \"backup_promotions\": " << totalBackupPromotions
      << ", \"failures_no_backup\": " << totalFailuresNoBackup
      << ", \"failures_backup_dead\": " << totalFailuresBackupDead
      << ", \"lost_during_failover\": " << totalLostDuringFailover
      << ", \"latest_failover_time_s\": "
      << nan(latestFailoverTime >= 0.0, latestFailoverTime)
      << ", \"retry_attempts\": " << totalRetryAttempts
      << ", \"retry_successes\": " << totalRetrySuccesses
      << ", \"promise_violations\": " << totalPromiseViolations
      << ", \"retry_exhaustions\": " << totalRetryExhaustions
      << ", \"rebootstrap_count\": " << totalRebootstrapCount << "},\n"
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
      "primary_failures,backup_promotions,failures_no_backup,failures_backup_dead,"
      "lost_during_failover,last_failover_time_s,"
      "visits,contacts,failed_contacts,discovery_contacts,"
      "windows_scheduled,windows_opened,windows_met,windows_missed,"
      "retry_attempts,retry_successes,promise_violations,retry_exhaustions,rebootstrap_count,"
      "wifi_awake_s,residual_fraction\n";
    for (size_t k = 0; k < K; ++k)
    {
        const auto& c = clusters[k];
        pc << c.id << "," << c.size << "," << c.generated << "," << c.delivered << "," << c.overflow
           << "," << c.lost154 << "," << c.sentWifi - c.delivered << "," << c.lostChDead << ","
           << c.buffer << "," << c.primaryFailures << "," << c.backupPromotions << ","
           << c.failuresNoBackup << "," << c.failuresBackupDead << ","
           << c.lostDuringFailover << "," << c.lastFailoverTime << ","
           << c.visits << "," << c.contacts << "," << c.failedContacts << ","
           << c.discoveryContacts << ","
           << c.windowsScheduled << "," << c.windowsOpened << ","
           << c.windowsMet << "," << c.windowsMissed << ","
           << c.retryAttempts << "," << c.retrySuccesses << "," << c.promiseViolations << ","
           << c.retryExhaustions << "," << c.rebootstrapCount << ","
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
