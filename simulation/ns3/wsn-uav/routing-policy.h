#ifndef WSN_UAV_ROUTING_POLICY_H
#define WSN_UAV_ROUTING_POLICY_H

#include "world.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
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
};

class RoutingPolicy
{
  public:
    virtual ~RoutingPolicy() = default;

    virtual uint32_t Next(const World& w,
                          const std::vector<ClusterBelief>& beliefs,
                          double currentX,
                          double currentY,
                          uint32_t currentCluster) = 0;

    virtual bool CommitsToOrder() const = 0;

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
                  uint32_t) override
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

// Select the nearest cluster, excluding the current cluster.
// If the nearest choice would cause A-B-A ping-pong, prefer the next
// nearest alternative when one exists.
class NearestFeasiblePolicy : public RoutingPolicy
{
  public:
    uint32_t Next(const World& w,
                  const std::vector<ClusterBelief>&,
                  double currentX,
                  double currentY,
                  uint32_t currentCluster) override
    {
        uint32_t best = UINT32_MAX;
        uint32_t bestAlternative = UINT32_MAX;
        double bestDistance = std::numeric_limits<double>::max();
        double alternativeDistance = std::numeric_limits<double>::max();

        for (const Cluster& c : w.clusters)
        {
            if (c.id == currentCluster)
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

        const uint32_t selected =
            (bestAlternative != UINT32_MAX) ? bestAlternative : best;

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
                  uint32_t currentCluster) override
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
                  uint32_t currentCluster) override
    {
        const uint32_t unexplored = SelectUncontacted(w, beliefs, currentX, currentY, currentCluster);

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

    NS_FATAL_ERROR("Unknown routing policy '" << name
                   << "' (available: tour, nearest-feasible, data-greedy, energy-data-score)");
}

} // namespace wsnuav

#endif