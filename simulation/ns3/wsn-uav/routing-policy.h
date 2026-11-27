
#ifndef WSN_UAV_ROUTING_POLICY_H
#define WSN_UAV_ROUTING_POLICY_H

#include "world.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace wsnuav
{

// UAV's estimated knowledge about a cluster.
// These are estimates from the last contact, NOT the simulator's true buffer.
struct ClusterBelief
{
    double estimatedBuffer = 0.0;       // readings
    double estimatedGenerationRate = 0.0; // readings/second
    double residualEnergy = 0.0;        // joules, last observed
    double timeSinceContact = 0.0;      // seconds
    double timeUntilPromise = -1.0;     // seconds; -1 means no promise
    uint32_t missedMeetings = 0;
    bool neverContacted = true;
    double lateQuantile = 0.0;          // seconds; ETA-lateness quantile if visited next
};

class RoutingPolicy
{
  public:
    virtual ~RoutingPolicy() = default;

    virtual uint32_t Next(const World& w,
                          const std::vector<ClusterBelief>& beliefs,
                          double currentX,
                          double currentY,
                          uint32_t currentCluster,
                          double halfLapThreshold) = 0;

    virtual bool CommitsToOrder() const = 0;

    // Length of the promise made at the cluster returned by the last Next(), as a multiple of
    // the promise period P (D7). Fixed policies keep P.
    virtual double PromiseFactor() const
    {
        return 1.0;
    }

    // Called once when the UAV application stops (end of the mission horizon).
    virtual void OnEpisodeEnd(const World&)
    {
    }

  protected:
    // Avoid A-B-A ping-pong when another cluster is available.
    bool IsPingPongCandidate(uint32_t candidate) const
    {
        return m_previousCluster != UINT32_MAX &&
               m_previousPreviousCluster == candidate;
    }

    // Visit never-contacted clusters before exploiting known cluster data.
    uint32_t SelectUncontacted(const World& w,
                               const std::vector<ClusterBelief>& beliefs,
                               double currentX,
                               double currentY,
                               uint32_t currentCluster) const
    {
        uint32_t best = UINT32_MAX;
        uint32_t bestAlternative = UINT32_MAX;

        double bestDistance = std::numeric_limits<double>::max();
        double alternativeDistance = std::numeric_limits<double>::max();

        for (const Cluster& c : w.clusters)
        {
            if (c.id == currentCluster || !beliefs.at(c.id).neverContacted)
                continue;

            const double dx = c.meetX - currentX;
            const double dy = c.meetY - currentY;
            const double distance = std::hypot(dx, dy);

            if (distance < bestDistance)
            {
                bestDistance = distance;
                best = c.id;
            }

            if (!IsPingPongCandidate(c.id) && distance < alternativeDistance)
            {
                alternativeDistance = distance;
                bestAlternative = c.id;
            }
        }

        return (bestAlternative != UINT32_MAX) ? bestAlternative : best;
    }

    void Remember(uint32_t selected)
    {
        m_previousPreviousCluster = m_previousCluster;
        m_previousCluster = selected;
    }

  private:
    uint32_t m_previousCluster = UINT32_MAX;
    uint32_t m_previousPreviousCluster = UINT32_MAX;
};

// Existing fixed survey tour.
class TourPolicy : public RoutingPolicy
{
  public:
    uint32_t Next(const World& w,
                  const std::vector<ClusterBelief>&,
                  double,
                  double,
                  uint32_t,
                  double) override
    {
        return w.tourOrder[m_i++ % w.tourOrder.size()];
    }

    bool CommitsToOrder() const override
    {
        return true;
    }

  private:
    size_t m_i = 0;
};

// Select the nearest feasible cluster, falling back to the
// longest-unvisited cluster when none is feasible.
class NearestFeasiblePolicy : public RoutingPolicy
{
  public:
    uint32_t Next(const World& w,
                  const std::vector<ClusterBelief>& beliefs,
                  double currentX,
                  double currentY,
                  uint32_t currentCluster,
                  double halfLapThreshold) override
    {
        const uint32_t unexplored =
            SelectUncontacted(w, beliefs, currentX, currentY, currentCluster);

        if (unexplored != UINT32_MAX)
        {
            Remember(unexplored);
            return unexplored;
        }

        uint32_t bestFeasible = UINT32_MAX;
        uint32_t longestUnvisited = UINT32_MAX;

        double bestDistance = std::numeric_limits<double>::max();
        double longestContactAge = -1.0;
        double fallbackDistance = std::numeric_limits<double>::max();

        for (const Cluster& c : w.clusters)
        {
            if (c.id == currentCluster)
                continue;

            const ClusterBelief& belief = beliefs.at(c.id);

            const double dx = c.meetX - currentX;
            const double dy = c.meetY - currentY;
            const double distance = std::hypot(dx, dy);

            // Never-contacted clusters are also feasible.
            const bool feasible =
                belief.neverContacted ||
                belief.timeSinceContact >= halfLapThreshold;

            if (feasible && distance < bestDistance)
            {
                bestDistance = distance;
                bestFeasible = c.id;
            }

            // Keep the longest-unvisited cluster as a fallback.
            if (belief.timeSinceContact > longestContactAge ||
                (belief.timeSinceContact == longestContactAge &&
                 distance < fallbackDistance))
            {
                longestContactAge = belief.timeSinceContact;
                fallbackDistance = distance;
                longestUnvisited = c.id;
            }
        }

        const uint32_t selected =
            (bestFeasible != UINT32_MAX) ? bestFeasible : longestUnvisited;

        NS_ABORT_MSG_IF(selected == UINT32_MAX,
                        "Nearest-feasible policy found no cluster other than current cluster");

        Remember(selected);
        return selected;
    }

    bool CommitsToOrder() const override
    {
        return false;
    }
};

// Select the cluster with the largest estimated amount of buffered data.
class DataGreedyPolicy : public RoutingPolicy
{
  public:
    uint32_t Next(const World& w,
                  const std::vector<ClusterBelief>& beliefs,
                  double currentX,
                  double currentY,
                  uint32_t currentCluster,
                  double halfLapThreshold) override
    {
        const uint32_t unexplored =
            SelectUncontacted(w, beliefs, currentX, currentY, currentCluster);

        if (unexplored != UINT32_MAX)
        {
            Remember(unexplored);
            return unexplored;
        }

        uint32_t best = UINT32_MAX;
        uint32_t bestAlternative = UINT32_MAX;
        double bestData = -1.0;
        double alternativeData = -1.0;

        for (const Cluster& c : w.clusters)
        {
            if (c.id == currentCluster)
                continue;

            const double data = beliefs.at(c.id).estimatedBuffer;

            if (data > bestData)
            {
                bestData = data;
                best = c.id;
            }

            if (!IsPingPongCandidate(c.id) && data > alternativeData)
            {
                alternativeData = data;
                bestAlternative = c.id;
            }
        }

        const uint32_t selected =
            (bestAlternative != UINT32_MAX) ? bestAlternative : best;

        NS_ABORT_MSG_IF(selected == UINT32_MAX,
                        "Data-greedy policy found no cluster other than current cluster");

        Remember(selected);
        return selected;
    }

    bool CommitsToOrder() const override
    {
        return false;
    }
};

// Balance estimated buffered data against the CH's last observed residual energy.
// Both quantities are normalised across the candidate clusters.
class EnergyDataPolicy : public RoutingPolicy
{
  public:
    uint32_t Next(const World& w,
                  const std::vector<ClusterBelief>& beliefs,
                  double currentX,
                  double currentY,
                  uint32_t currentCluster,
                  double halfLapThreshold) override
    {
        const uint32_t unexplored =
            SelectUncontacted(w, beliefs, currentX, currentY, currentCluster);

        if (unexplored != UINT32_MAX)
        {
            Remember(unexplored);
            return unexplored;
        }

        double maxData = 0.0;
        double maxEnergy = 0.0;

        for (const Cluster& c : w.clusters)
        {
            if (c.id == currentCluster)
                continue;

            const ClusterBelief& b = beliefs.at(c.id);
            maxData = std::max(maxData, b.estimatedBuffer);
            maxEnergy = std::max(maxEnergy, b.residualEnergy);
        }

        uint32_t best = UINT32_MAX;
        uint32_t bestAlternative = UINT32_MAX;
        double bestScore = -1.0;
        double alternativeScore = -1.0;

        for (const Cluster& c : w.clusters)
        {
            if (c.id == currentCluster)
                continue;

            const ClusterBelief& b = beliefs.at(c.id);

            const double dataScore =
                (maxData > 0.0) ? b.estimatedBuffer / maxData : 0.0;
            const double energyScore =
                (maxEnergy > 0.0) ? b.residualEnergy / maxEnergy : 0.0;

            // Equal weighting: prioritise data availability while avoiding
            // repeatedly visiting a cluster whose CH has very little energy.
            const double score = 0.5 * dataScore + 0.5 * energyScore;

            if (score > bestScore)
            {
                bestScore = score;
                best = c.id;
            }

            if (!IsPingPongCandidate(c.id) && score > alternativeScore)
            {
                alternativeScore = score;
                bestAlternative = c.id;
            }
        }

        const uint32_t selected =
            (bestAlternative != UINT32_MAX) ? bestAlternative : best;

        NS_ABORT_MSG_IF(selected == UINT32_MAX,
                        "Energy-data policy found no cluster other than current cluster");

        Remember(selected);
        return selected;
    }

    bool CommitsToOrder() const override
    {
        return false;
    }
};

// Decisions come from an outside process (Phase 3 PPO, routing/env.py) over two pipes.
// When enabled, the first K decisions are the fixed survey lap (proposal Algorithm 1).
// When disabled (A9), PPO makes a routing decision from the very first visit.
// At every PPO decision the policy writes one line
//   D now current x y | totals | K x (cluster features)
// and reads back "<cluster id> [promise factor]" (factor defaults to 1). At the end of the
// mission it writes "E | totals".
// Only UAV-side knowledge is sent: last-contact beliefs, promises, and static meeting points.
// The totals are running counters used by the trainer for the reward, never as observations.
class ExternalPolicy : public RoutingPolicy
{
  public:
    ~ExternalPolicy() override
    {
        if (m_in)
            std::fclose(m_in);
        if (m_out)
            std::fclose(m_out);
    }

    uint32_t Next(const World& w,
                  const std::vector<ClusterBelief>& beliefs,
                  double currentX,
                  double currentY,
                  uint32_t currentCluster,
                  double) override
    {
        m_factor = 1.0;

        // A9: skip the mandatory initial survey lap when disabled.
        if (w.cfg.enableSurveyLap && m_decisions < w.tourOrder.size())
        {
            return w.tourOrder[m_decisions++];
        }

        m_decisions++;
        Open(w);

        std::fprintf(m_out,
                     "D %.6f %d %.3f %.3f |",
                     ns3::Simulator::Now().GetSeconds(),
                     currentCluster == UINT32_MAX ? -1 : static_cast<int>(currentCluster),
                     currentX,
                     currentY);
        WriteTotals(w);
        std::fprintf(m_out, " |");

        for (const Cluster& c : w.clusters)
        {
            const ClusterBelief& b = beliefs.at(c.id);
            std::fprintf(m_out,
                         " %.3f %.3f %.6g %.6g %.6g %.6g %.6g %u %d %.6g",
                         c.meetX,
                         c.meetY,
                         b.estimatedBuffer,
                         b.estimatedGenerationRate,
                         b.residualEnergy,
                         b.timeSinceContact,
                         b.timeUntilPromise,
                         b.missedMeetings,
                         b.neverContacted ? 1 : 0,
                         b.lateQuantile);
        }

        std::fprintf(m_out, "\n");
        std::fflush(m_out);

        char line[64];
        NS_ABORT_MSG_IF(!std::fgets(line, sizeof(line), m_in), "external routing: bridge closed");

        char* end = nullptr;
        const long k = std::strtol(line, &end, 10);

        NS_ABORT_MSG_IF(end == line || k < 0 || static_cast<size_t>(k) >= w.clusters.size() ||
                            static_cast<uint32_t>(k) == currentCluster,
                        "external routing: invalid decision '" << line << "'");

        char* rest = end;
        const double factor = std::strtod(end, &rest);

        if (rest != end)
        {
            NS_ABORT_MSG_IF(!(factor > 0.0), "external routing: invalid promise factor '" << line << "'");
            m_factor = factor;
        }

        return static_cast<uint32_t>(k);
    }

    void OnEpisodeEnd(const World& w) override
    {
        if (!m_out)
        {
            return; // no PPO decision was made during the episode
        }

        std::fprintf(m_out, "E |");
        WriteTotals(w);
        std::fprintf(m_out, "\n");
        std::fflush(m_out);
    }

    bool CommitsToOrder() const override
    {
        return false;
    }

    double PromiseFactor() const override
    {
        return m_factor;
    }

  private:
    void Open(const World& w)
    {
        if (m_out)
        {
            return;
        }

        NS_ABORT_MSG_IF(w.cfg.bridgeFdIn < 0 || w.cfg.bridgeFdOut < 0,
                        "routing=external needs --bridgeFdIn and --bridgeFdOut");

        m_in = fdopen(w.cfg.bridgeFdIn, "r");
        m_out = fdopen(w.cfg.bridgeFdOut, "w");

        NS_ABORT_MSG_IF(!m_in || !m_out, "external routing: cannot open bridge descriptors");
    }

    // delivered generated windows_missed retry_successes flight_s hover_s ch_wifi_J
    void WriteTotals(const World& w) const
    {
        uint64_t delivered = 0, generated = 0;
        uint32_t missed = 0, retried = 0;

        for (const Cluster& c : w.clusters)
        {
            delivered += c.delivered;
            generated += c.generated;
            missed += c.windowsMissed;
            retried += c.retrySuccesses;
        }

        double wifiJ = 0.0;

        for (const Sensor& s : w.sensors)
        {
            if (s.wifiEnergy)
            {
                wifiJ += s.wifiEnergy->GetTotalEnergyConsumption();
            }
        }

        std::fprintf(m_out,
                     " %llu %llu %u %u %.6f %.6f %.6f",
                     static_cast<unsigned long long>(delivered),
                     static_cast<unsigned long long>(generated),
                     missed,
                     retried,
                     w.uavFlightTime,
                     w.uavHoverTime,
                     wifiJ);
    }

    size_t m_decisions = 0;
    double m_factor = 1.0;
    std::FILE* m_in = nullptr;
    std::FILE* m_out = nullptr;
};

inline std::unique_ptr<RoutingPolicy>
MakeRoutingPolicy(const std::string& name)
{
    if (name == "tour")
        return std::make_unique<TourPolicy>();

    if (name == "nearest-feasible")
        return std::make_unique<NearestFeasiblePolicy>();

    if (name == "data-greedy")
        return std::make_unique<DataGreedyPolicy>();

    if (name == "energy-data-score")
        return std::make_unique<EnergyDataPolicy>();

    if (name == "external")
        return std::make_unique<ExternalPolicy>();

    NS_FATAL_ERROR("Unknown routing policy '" << name
                   << "' (available: tour, nearest-feasible, data-greedy, energy-data-score, external)");
}

} // namespace wsnuav

#endif
