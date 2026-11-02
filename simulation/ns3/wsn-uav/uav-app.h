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

  private:
    void StartApplication() override;
    void StopApplication() override;

    void Depart();
    void Arrive();
    void SendPoll();
    void ContactTimeout();
    void EndHover();
    void Receive(ns3::Ptr<ns3::Socket> socket);

    // Periodic timetable for a policy that commits to the tour order (D7). Lap 0 is the survey
    // lap (hover budget dutyPeriod + dutyListen, CHs in DISCOVERY); later laps budget hoverBudget
    // per stop. Legs are planned at planSpeedFactor * uavSpeed so that late arrivals recover.
    void BuildTimetable(ns3::Vector depot);
    // Planned arrival time at cluster k in lap `lap` (0-based) [s].
    double Slot(uint32_t k, uint32_t lap) const;

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
    std::vector<double> m_lap0, m_offset; // per tour position [s]
    double m_lap1Start = 0, m_period = 0;  // [s]
    double m_lastWaypoint = 0.0;   // time of the last waypoint added [s]

    ns3::EventId m_pollEvent;
    ns3::EventId m_waitEvent;
    ns3::EventId m_capEvent;
    ns3::EventId m_endEvent;
};

} // namespace wsnuav

#endif
