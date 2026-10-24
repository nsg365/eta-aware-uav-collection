// Next-cluster selection policies for the UAV. Only the fixed tour exists so far; Phase 2 adds
// nearest-feasible and data-greedy here, Phase 3 an external (PPO) policy.
#ifndef WSN_UAV_ROUTING_POLICY_H
#define WSN_UAV_ROUTING_POLICY_H

#include "world.h"

#include <memory>
#include <string>

namespace wsnuav
{

class RoutingPolicy
{
  public:
    virtual ~RoutingPolicy() = default;
    virtual uint32_t Next(const World& w) = 0;
    // A policy that commits to a periodic visit order can promise the next arrival at a
    // cluster at contact time, which the scheduled wake mode requires (docs: D7).
    virtual bool CommitsToOrder() const = 0;
};

// Cycles through the survey tour (nearest-neighbour + 2-opt order computed in Phase 0).
class TourPolicy : public RoutingPolicy
{
  public:
    uint32_t Next(const World& w) override
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

inline std::unique_ptr<RoutingPolicy>
MakeRoutingPolicy(const std::string& name)
{
    if (name == "tour")
    {
        return std::make_unique<TourPolicy>();
    }
    NS_FATAL_ERROR("Unknown routing policy '" << name << "' (available: tour)");
}

} // namespace wsnuav

#endif
