#include "uav-app.h"

#include "ns3/inet-socket-address.h"
#include "ns3/log.h"
#include "ns3/simulator.h"
#include "ns3/udp-socket-factory.h"

#include <algorithm>
#include <cmath>

NS_LOG_COMPONENT_DEFINE("WsnUavUav");

namespace wsnuav
{

using namespace ns3;

namespace
{
constexpr double END_GUARD = 0.05; // time to let the PLAN frame leave before departing [s]
} // namespace

UavApp::UavApp(World* world,
               std::unique_ptr<RoutingPolicy> policy,
               Ptr<NormalRandomVariable> speed,
               Ptr<UniformRandomVariable> delay)
    : m_w(world),
      m_policy(std::move(policy)),
      m_speed(speed),
      m_delay(delay),
      m_promise(world->clusters.size(), -1.0)
{
}

void
UavApp::StartApplication()
{
    m_mob = GetNode()->GetObject<WaypointMobilityModel>();
    NS_ABORT_MSG_IF(!m_mob, "UAV node needs a WaypointMobilityModel");
    m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
    m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), UAV_PORT));
    m_socket->SetAllowBroadcast(true);
    m_socket->SetRecvCallback(MakeCallback(&UavApp::Receive, this));
    if (m_policy->CommitsToOrder())
    {
        BuildTimetable(m_mob->GetPosition());
    }
    Depart();
}

void
UavApp::StopApplication()
{
    if (m_hovering)
    {
        m_w->uavHoverTime += Simulator::Now().GetSeconds() - m_visit.arriveTime;
    }
    m_pollEvent.Cancel();
    m_waitEvent.Cancel();
    m_capEvent.Cancel();
    m_endEvent.Cancel();
}


void
UavApp::Depart()
{
    const SimConfig& cfg = m_w->cfg;
    double now = Simulator::Now().GetSeconds();
    uint32_t k = m_policy->Next(*m_w);
    const Cluster& c = m_w->clusters[k];

    Vector from = m_mob->GetPosition();
    Vector to(c.meetX, c.meetY, cfg.uavAltitude);
    double d = CalculateDistance(from, to);
    double v = std::max(cfg.uavMinSpeed, m_speed->GetValue());
    double flightTime = d / v;

    // Independently decide whether this flight leg experiences an extra delay.
    double delay = 0.0;
    if (m_delay->GetValue() < cfg.uavDelayProb)
    {
        delay = cfg.uavDelayMin + m_delay->GetValue() * (cfg.uavDelayMax - cfg.uavDelayMin);
    }

    double totalTime = flightTime + delay;

    // Pin the current position so the mobility model does not interpolate
    // across the previous hover.
    if (now > m_lastWaypoint)
    {
        m_mob->AddWaypoint(Waypoint(Seconds(now), from));
    }

    m_lastWaypoint = now + totalTime;
    m_mob->AddWaypoint(Waypoint(Seconds(now + totalTime), to));

    m_w->uavDistance += d;
    m_w->uavFlightTime += totalTime;
    m_w->uavDelayTime += delay;

    m_visit = VisitRecord{
        k, now, now + totalTime, -1.0, -1.0, d, m_promise[k], 0
    };
    m_promise[k] = -1.0;

    Simulator::Schedule(Seconds(totalTime), &UavApp::Arrive, this);
}

void
UavApp::Arrive()
{
    const SimConfig& cfg = m_w->cfg;
    Cluster& c = m_w->clusters[m_visit.cluster];
    c.visits++;
    m_hovering = true;
    m_contact = false;
    m_planSent = false;
    SendPoll();
    // Under a committed timetable the UAV is never more than w ahead of its slot: an early UAV
    // holds (in every lap, so lap 0 cannot leave it a lap ahead), and the contact timeout and
    // hover cap count from the end of the hold (D8).
    double hold = 0;
    if (m_policy->CommitsToOrder())
    {
        double opens = Slot(m_visit.cluster, c.visits - 1) - cfg.wakeHalfWidth;
        hold = std::max(0.0, opens - Simulator::Now().GetSeconds());
    }
    m_waitEvent = Simulator::Schedule(Seconds(hold + cfg.contactWait), &UavApp::ContactTimeout, this);
    m_capEvent = Simulator::Schedule(Seconds(hold + cfg.maxHover), &UavApp::EndHover, this);
}

void
UavApp::SendPoll()
{
    if (!m_hovering || m_contact)
    {
        return;
    }
    Msg m;
    m.type = MsgType::POLL;
    m.cluster = m_visit.cluster;
    m_socket->SendTo(MakePacket(m), 0, InetSocketAddress(Ipv4Address::GetBroadcast(), CH_PORT));
    m_pollEvent = Simulator::Schedule(Seconds(m_w->cfg.beaconInterval), &UavApp::SendPoll, this);
}

void
UavApp::ContactTimeout()
{
    m_w->clusters[m_visit.cluster].failedContacts++;
    EndHover();
}

void
UavApp::EndHover()
{
    if (!m_hovering)
    {
        return;
    }
    m_pollEvent.Cancel();
    m_waitEvent.Cancel();
    m_capEvent.Cancel();
    m_endEvent.Cancel();
    m_hovering = false;
    double now = Simulator::Now().GetSeconds();
    double hover = now - m_visit.arriveTime;
    m_w->uavHoverTime += hover;
    m_visit.endTime = now;
    m_w->visits.push_back(m_visit);
    Depart();
}

void
UavApp::BuildTimetable(Vector depot)
{
    const SimConfig& cfg = m_w->cfg;
    const auto& order = m_w->tourOrder;
    const size_t K = order.size();
    const double vPlan = cfg.planSpeedFactor * cfg.uavSpeed;
    const double surveyBudget = cfg.dutyPeriod + cfg.dutyListen; // CHs are in DISCOVERY on lap 0
    auto meet = [&](size_t i) { return m_w->clusters[order[i]]; };
    auto leg = [&](size_t i, size_t j) {
        return std::hypot(meet(j).meetX - meet(i).meetX, meet(j).meetY - meet(i).meetY) / vPlan;
    };

    m_lap0.assign(K, 0.0);
    m_offset.assign(K, 0.0);
    m_lap0[0] = std::hypot(meet(0).meetX - depot.x, meet(0).meetY - depot.y) / vPlan;
    for (size_t i = 1; i < K; ++i)
    {
        m_lap0[i] = m_lap0[i - 1] + surveyBudget + leg(i - 1, i);
        m_offset[i] = m_offset[i - 1] + cfg.hoverBudget + leg(i - 1, i);
    }
    m_lap1Start = m_lap0[K - 1] + surveyBudget + leg(K - 1, 0);
    m_period = m_offset[K - 1] + cfg.hoverBudget + leg(K - 1, 0);
}

double
UavApp::Slot(uint32_t k, uint32_t lap) const
{
    size_t i = m_w->clusters[k].tourIndex;
    return lap == 0 ? m_lap0[i] : m_lap1Start + (lap - 1) * m_period + m_offset[i];
}

void
UavApp::Receive(Ptr<Socket> socket)
{
    Address from;
    Ptr<Packet> p;
    while ((p = socket->RecvFrom(from)))
    {
        Msg m;
        if (!ParsePacket(p, m) || m.cluster >= m_w->clusters.size())
        {
            continue;
        }
        Cluster& c = m_w->clusters[m.cluster];
        if (m.type == MsgType::DATA)
        {
            c.delivered += m.count; // counted even if it arrives late, it reached the UAV
        }
        bool current = m_hovering && m.cluster == m_visit.cluster;
        if (!current || (m.type != MsgType::DATA && m.type != MsgType::DONE))
        {
            continue;
        }
        if (!m_contact)
        {
            m_contact = true;
            m_visit.contactTime = Simulator::Now().GetSeconds();
            m_waitEvent.Cancel();
            c.contacts++;
        }
        if (m.type == MsgType::DATA)
        {
            m_visit.readings += m.count;
        }
        else if (!m_planSent)
        {
            m_planSent = true;
            if (m_w->cfg.wakeMode == "scheduled")
            {
                // Promise the cluster's slot in the next lap of the committed timetable (D7).
                double eta = Slot(m.cluster, c.visits);
                m_promise[m.cluster] = eta;
                Msg plan;
                plan.type = MsgType::PLAN;
                plan.cluster = m.cluster;
                plan.timeNs = static_cast<int64_t>(eta * 1e9);
                plan.halfWidthNs = static_cast<int64_t>(m_w->cfg.wakeHalfWidth * 1e9);
                Address ch = InetSocketAddress(InetSocketAddress::ConvertFrom(from).GetIpv4(), CH_PORT);
                m_socket->SendTo(MakePacket(plan), 0, ch);
            }
            m_endEvent = Simulator::Schedule(Seconds(END_GUARD), &UavApp::EndHover, this);
        }
    }
}

} // namespace wsnuav
