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
      m_promise(world->clusters.size(), -1.0),
      m_contacted(world->clusters.size(), false)
{
    m_activePrimary.reserve(world->clusters.size());
    for (const auto& cluster : world->clusters)
    {
        m_activePrimary.push_back(cluster.primary);
    }
}

void
UavApp::SetActivePrimary(uint32_t clusterId, uint32_t sensorId)
{
    if (clusterId >= m_activePrimary.size())
    {
        NS_LOG_WARN("Invalid cluster ID in SetActivePrimary: " << clusterId);
        return;
    }

    m_activePrimary[clusterId] = sensorId;

    NS_LOG_INFO(
        Simulator::Now().GetSeconds()
        << "s UAV updated active primary for cluster "
        << clusterId << " to sensor " << sensorId);
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
    m_period = PromisePeriod();
    m_uncontacted = static_cast<uint32_t>(m_w->clusters.size());
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
    // The contact timeout and hover cap count from the end of the hold (D8).
    double hold = HoldFor(m_visit.promisedEta, Simulator::Now().GetSeconds());
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

// P: one tour lap with legs at planSpeedFactor * uavSpeed plus hoverBudget per stop (D7).
double
UavApp::PromisePeriod() const
{
    const SimConfig& cfg = m_w->cfg;
    const auto& order = m_w->tourOrder;
    const double vPlan = cfg.planSpeedFactor * cfg.uavSpeed;
    double period = 0;
    for (size_t i = 0; i < order.size(); ++i)
    {
        const Cluster& a = m_w->clusters[order[i]];
        const Cluster& b = m_w->clusters[order[(i + 1) % order.size()]];
        period += cfg.hoverBudget + std::hypot(b.meetX - a.meetX, b.meetY - a.meetY) / vPlan;
    }
    return period;
}

// How long to hold at the meeting point so the CH is listening (D8). An early UAV waits for the
// promised window [tau - w, tau + w]; a late one waits for the next retry window, which opens at
// tau + w + m * retryInterval for m = 1..maxMissedRetries and lasts retryListen. After the last
// retry the CH is back in DISCOVERY and no hold is needed.
double
UavApp::HoldFor(double promised, double now) const
{
    const SimConfig& cfg = m_w->cfg;
    if (promised < 0 || cfg.wakeMode != "scheduled")
    {
        return 0;
    }
    if (now < promised - cfg.wakeHalfWidth)
    {
        return promised - cfg.wakeHalfWidth - now;
    }
    double end = promised + cfg.wakeHalfWidth;
    if (now <= end)
    {
        return 0;
    }
    for (uint32_t m = 1; m <= cfg.maxMissedRetries; ++m)
    {
        double opens = end + m * cfg.retryInterval;
        if (now < opens)
        {
            return opens - now;
        }
        if (now <= opens + cfg.retryListen)
        {
            return 0;
        }
    }
    return 0;
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

        // Ignore packets from a CH that is no longer the active primary.
        if ((m.type == MsgType::DATA || m.type == MsgType::DONE) &&
            m.primaryId != m_activePrimary[m.cluster])
        {
            continue;
        }

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
            if (!m_contacted[m.cluster])
            {
                m_contacted[m.cluster] = true;
                m_uncontacted--;
            }
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
                // Promise to be back one lap from now (D7). Clusters not yet contacted are
                // still in DISCOVERY, where the UAV waits T_b / 2 on average for the CH to
                // listen, not hoverBudget; this only lengthens promises made in the survey lap.
                // (The worst case, T_b + t_l per stop, over-promises early clusters, and the
                // UAV's hold there then makes the rest of the next lap late.)
                const SimConfig& cfg = m_w->cfg;
                double surveyExtra = std::max(0.0, 0.5 * cfg.dutyPeriod - cfg.hoverBudget);
                double eta = Simulator::Now().GetSeconds() + END_GUARD + m_period +
                             m_uncontacted * surveyExtra;
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
