// UAV data-mule application: flies between meeting points (WaypointMobilityModel), polls the
// cluster's CH while hovering, receives buffered readings, and (scheduled wake mode) hands the
// CH a PLAN with the promised next arrival time.
//
// Flight/hover energy is the analytic abstraction of eq. (9); the UAV battery is not limited
// yet (no depot return).
#ifndef WSN_UAV_UAV_APP_H
#define WSN_UAV_UAV_APP_H

#include "protocol.h"
#include "routing-policy.h"
#include "world.h"
#include <map>

#include "ns3/application.h"
#include "ns3/random-variable-stream.h"
#include "ns3/socket.h"
#include "ns3/waypoint-mobility-model.h"

namespace wsnuav
{

class UavApp : public ns3::Application
{
  public:
    UavApp(World* world,
       std::unique_ptr<RoutingPolicy> policy,
       ns3::Ptr<ns3::NormalRandomVariable> speed,
       ns3::Ptr<ns3::UniformRandomVariable> delay);

    void SetActivePrimary(uint32_t clusterId, uint32_t sensorId);

  private:
    void StartApplication() override;
    void StopApplication() override;

    void Depart();
    std::vector<double> BuildBeliefVector() const;
    void Arrive();
    void SendPoll();
    void ContactTimeout();
    void EndHover();
    void Receive(ns3::Ptr<ns3::Socket> socket);

    // Periodic timetable for a policy that commits to the tour order (D7).
    void BuildTimetable(ns3::Vector depot);
    // Calculate the nominal reference-tour period [s], independent of routing policy.
    void CalculateNominalPeriod(ns3::Vector depot);
    // Planned arrival time at cluster k in lap `lap` (0-based) [s].
    double Slot(uint32_t k, uint32_t lap) const;
    // Promise period P (D7) and the hold at a meeting point (D8).
    double PromisePeriod() const;
    double HoldFor(double promised, double now) const;

    World* m_w;
    std::unique_ptr<RoutingPolicy> m_policy;
    ns3::Ptr<ns3::NormalRandomVariable> m_speed;
    ns3::Ptr<ns3::UniformRandomVariable> m_delay;
    ns3::Ptr<ns3::WaypointMobilityModel> m_mob;
    ns3::Ptr<ns3::Socket> m_socket;

    bool m_hovering = false;
    bool m_contact = false;
    bool m_planSent = false;
    VisitRecord m_visit{};
    std::vector<double> m_promise; // per cluster, promised next arrival (-1 none)
    std::vector<double> m_lastContactBuffer;
    std::vector<double> m_lastContactEnergy;
    std::vector<double> m_lastContactTime;
    std::vector<double> m_estimatedGenerationRate;
    std::vector<uint32_t> m_missedMeetings;
    std::vector<bool> m_neverContacted;
    std::vector<uint32_t> m_activePrimary; // active CH sensor ID per cluster
    std::vector<double> m_lap0, m_offset; // per tour position [s]
    std::vector<uint64_t> m_arrivalsAtPromise;
    std::vector<uint32_t> m_lastStopsSincePromise;
    std::map<uint32_t, std::vector<double>> m_latenessByStops;
    uint64_t m_totalArrivals = 0;
    double m_lap1Start = 0; // [s]
    double m_period = 0; // promise horizon [s]
    double m_nominalPeriod = 0.0; // common reference-tour period for all policies [s]
    std::vector<bool> m_contacted; // per cluster, contacted at least once
    uint32_t m_uncontacted = 0;
    double m_lastWaypoint = 0.0;   // time of the last waypoint added [s]

    ns3::EventId m_pollEvent;
    ns3::EventId m_delayedPollEvent;
    ns3::EventId m_waitEvent;
    ns3::EventId m_capEvent;
    ns3::EventId m_endEvent;
};

} // namespace wsnuav

#endif
