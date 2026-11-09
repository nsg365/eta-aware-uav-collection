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

double
CalculateQuantile(std::vector<double> values, double quantile)
{
    if (values.empty())
    {
        return 0.0;
    }

    std::sort(values.begin(), values.end());

    const double position = quantile * (values.size() - 1);
    const size_t lower = static_cast<size_t>(std::floor(position));
    const size_t upper = static_cast<size_t>(std::ceil(position));

    if (lower == upper)
    {
        return values[lower];
    }

    const double fraction = position - lower;
    return values[lower] * (1.0 - fraction) + values[upper] * fraction;
}
} // namespace

// UavApp::UavApp(World* world,
//                std::unique_ptr<RoutingPolicy> policy,
//                Ptr<NormalRandomVariable> speed,
//                Ptr<UniformRandomVariable> delay)
//     : m_w(world),
//       m_policy(std::move(policy)),
//       m_speed(speed),
//       m_delay(delay),
//       m_promise(world->clusters.size(), -1.0)
// {
//     m_activePrimary.reserve(world->clusters.size());
//     for (const auto& cluster : world->clusters)
//     {
//         m_activePrimary.push_back(cluster.primary);
//     }
// }

UavApp::UavApp(World* world,
               std::unique_ptr<RoutingPolicy> policy,
               Ptr<NormalRandomVariable> speed,
               Ptr<UniformRandomVariable> delay)
    : m_w(world),
      m_policy(std::move(policy)),
      m_speed(speed),
      m_delay(delay),
      m_promise(world->clusters.size(), -1.0),
      m_lastContactBuffer(world->clusters.size(), 0.0),
      m_lastContactEnergy(world->clusters.size(), 0.0),
      m_lastContactTime(world->clusters.size(), -1.0),
      m_estimatedGenerationRate(world->clusters.size(), 0.0),
      m_missedMeetings(world->clusters.size(), 0),
      m_neverContacted(world->clusters.size(), true),
      m_arrivalsAtPromise(world->clusters.size(), 0),
      m_lastStopsSincePromise(world->clusters.size(), 0)
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
    CalculateNominalPeriod(m_mob->GetPosition());

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



std::vector<double>
UavApp::BuildBeliefVector() const
{
    constexpr std::size_t FEATURES_PER_CLUSTER = 7;

    const double now = Simulator::Now().GetSeconds();

    std::vector<double> state;
    state.reserve(m_w->clusters.size() * FEATURES_PER_CLUSTER);

    for (uint32_t i = 0; i < m_w->clusters.size(); ++i)
    {
        const double elapsed =
            (m_lastContactTime[i] >= 0.0)
                ? std::max(0.0, now - m_lastContactTime[i])
                : 0.0;

        const double estimatedBuffer =m_estimatedGenerationRate[i] * elapsed;


        const double timeUntilPromise =
            (m_promise[i] >= 0.0)
                ? m_promise[i] - now
                : -1.0;

        // Fixed feature order: 7 values per cluster.
        state.push_back(estimatedBuffer);
        state.push_back(m_estimatedGenerationRate[i]);
        state.push_back(m_lastContactEnergy[i]);
        state.push_back(elapsed);
        state.push_back(timeUntilPromise);
        state.push_back(static_cast<double>(m_missedMeetings[i]));
        state.push_back(m_neverContacted[i] ? 1.0 : 0.0);
    }

    return state;
}


void
UavApp::Depart()
{
    const SimConfig& cfg = m_w->cfg;
    double now = Simulator::Now().GetSeconds();

    const Vector currentPosition = m_mob->GetPosition();

    // std::vector<ClusterBelief> beliefs(m_w->clusters.size());

    // for (uint32_t i = 0; i < beliefs.size(); ++i)
    // {
    //     const double elapsed =
    //         (m_lastContactTime[i] >= 0.0)
    //             ? std::max(0.0, now - m_lastContactTime[i])
    //             : 0.0;

    //     beliefs[i].estimatedBuffer =
    //         m_lastContactBuffer[i] + m_estimatedGenerationRate[i] * elapsed;

    //     beliefs[i].estimatedGenerationRate = m_estimatedGenerationRate[i];
    //     beliefs[i].residualEnergy = m_lastContactEnergy[i];
    //     beliefs[i].timeSinceContact = elapsed;
    //     beliefs[i].timeUntilPromise =
    //         (m_promise[i] >= 0.0) ? m_promise[i] - now : -1.0;
    //     beliefs[i].missedMeetings = m_missedMeetings[i];
    //     beliefs[i].neverContacted = m_neverContacted[i];
    // }


    // Build the flat belief vector used as the Phase 3 observation interface.
    const std::vector<double> flatBeliefs = BuildBeliefVector();
    NS_ABORT_MSG_IF(flatBeliefs.size() != m_w->clusters.size() * 7, "Invalid UAV belief vector size");
    // Convert the flat vector into the structured representation
    // required by the existing routing policies.
    constexpr std::size_t FEATURES_PER_CLUSTER = 7;

    std::vector<ClusterBelief> beliefs(m_w->clusters.size());

    for (uint32_t i = 0; i < beliefs.size(); ++i)
    {
        const std::size_t offset = i * FEATURES_PER_CLUSTER;

        beliefs[i].estimatedBuffer = flatBeliefs[offset + 0];
        beliefs[i].estimatedGenerationRate = flatBeliefs[offset + 1];
        beliefs[i].residualEnergy = flatBeliefs[offset + 2];
        beliefs[i].timeSinceContact = flatBeliefs[offset + 3];
        beliefs[i].timeUntilPromise = flatBeliefs[offset + 4];
        beliefs[i].missedMeetings = static_cast<uint32_t>(flatBeliefs[offset + 5]);
        beliefs[i].neverContacted = (flatBeliefs[offset + 6] > 0.5);
    }

    const uint32_t currentCluster =
        (m_totalArrivals == 0) ? UINT32_MAX : m_visit.cluster;

    uint32_t k = m_policy->Next(
        *m_w, beliefs,
        currentPosition.x, currentPosition.y,
        currentCluster);

    const Cluster& c = m_w->clusters[k];

    // Keep the rest of your existing Depart() implementation unchanged.

    Vector from = m_mob->GetPosition();
    Vector to(c.meetX, c.meetY, cfg.uavAltitude);
    double d = CalculateDistance(from, to);
    double v = std::max(cfg.uavMinSpeed, m_speed->GetValue());
    double flightTime = d / v;

    // Independently decide whether this flight leg experiences an extra delay.

    // if (m_delay->GetValue() < cfg.uavDelayProb)
    // {
    //     delay = cfg.uavDelayMin + m_delay->GetValue() * (cfg.uavDelayMax - cfg.uavDelayMin);
    // }
    // Independently sample whether this leg is delayed.
    double delay = 0.0;
    const double delayEvent = m_delay->GetValue();

    if (delayEvent < cfg.uavDelayProb)
    {
        // Sample delay duration independently over [uavDelayMin, uavDelayMax].
        const double delayDuration = m_delay->GetValue();

        delay = cfg.uavDelayMin + delayDuration * (cfg.uavDelayMax - cfg.uavDelayMin);
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
        k, now, now + totalTime, -1.0, -1.0, d, m_promise[k],(m_promise[k] >= 0.0) ? m_lastContactTime[k] : -1.0, 0
    };
    m_promise[k] = -1.0;

    Simulator::Schedule(Seconds(totalTime), &UavApp::Arrive, this);
}

void
UavApp::Arrive()
{
    const SimConfig& cfg = m_w->cfg;
    Cluster& c = m_w->clusters[m_visit.cluster];
    // NS_LOG_UNCOND(
    //     "ARRIVE CHECK: cluster=" << m_visit.cluster
    //     << " promisedEta=" << m_visit.promisedEta
    //     << " now=" << Simulator::Now().GetSeconds());

    // Record positive lateness for the previous promise.
    if (m_visit.promisedEta >= 0.0)
    {
        const double lateness = std::max(
            0.0,
            Simulator::Now().GetSeconds() - m_visit.promisedEta);

        const uint64_t arrivalsSincePromise =
            m_totalArrivals - m_arrivalsAtPromise[m_visit.cluster];

        // const uint32_t stopsSincePromise =
        //     static_cast<uint32_t>(
        //         arrivalsSincePromise > 0 ? arrivalsSincePromise - 1 : 0);

        //const uint32_t stopsSincePromise = static_cast<uint32_t>(arrivalsSincePromise > 0 ? arrivalsSincePromise - 1 : 0);
        const uint32_t stopsSincePromise = static_cast<uint32_t>(arrivalsSincePromise);
        m_latenessByStops[stopsSincePromise].push_back(lateness);
    }
    m_totalArrivals++;
    c.visits++;
    m_hovering = true;
    m_contact = false;
    m_planSent = false;

    // In scheduled mode, wait until the promised listening window opens.
    // The promise is shared by all routing policies.
    double hold = 0.0;

    if (cfg.wakeMode == "scheduled" && m_visit.promisedEta >= 0.0)
    {
        const double opens = m_visit.promisedEta - cfg.wDrift - cfg.wakeHalfWidth;

        hold = std::max(
            0.0,
            opens - Simulator::Now().GetSeconds());
    }
    if (hold > 0.0)
    {
        m_delayedPollEvent = Simulator::Schedule(
            Seconds(hold),
            &UavApp::SendPoll,
            this);
    }
    else
    {
        SendPoll();
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
    m_missedMeetings[m_visit.cluster]++;
    EndHover();
}

void
UavApp::EndHover()
{
    if (!m_hovering)
    {
        return;
    }
    m_delayedPollEvent.Cancel();
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
UavApp::CalculateNominalPeriod(Vector depot)
{
    const SimConfig& cfg = m_w->cfg;
    const auto& order = m_w->tourOrder;
    const size_t K = order.size();

    NS_ABORT_MSG_IF(K == 0, "Cannot calculate nominal period with no clusters");

    const double vNominal = cfg.planSpeedFactor * cfg.uavSpeed;

    NS_ABORT_MSG_IF(vNominal <= 0.0, "Nominal UAV speed must be positive");

    double totalDistance = 0.0;

    // First leg: depot to the first cluster.
    // const Cluster& first = m_w->clusters[order[0]];

    // totalDistance += std::hypot(
    //     first.meetX - depot.x,
    //     first.meetY - depot.y);

    // Middle legs: between consecutive clusters.
    for (size_t i = 1; i < K; ++i)
    {
        const Cluster& previous = m_w->clusters[order[i - 1]];
        const Cluster& current = m_w->clusters[order[i]];

        totalDistance += std::hypot(
            current.meetX - previous.meetX,
            current.meetY - previous.meetY);
    }
    const Cluster& first = m_w->clusters[order[0]];
    // Final leg: from the last cluster back to the first.
    const Cluster& last = m_w->clusters[order[K - 1]];

    totalDistance += std::hypot(
        first.meetX - last.meetX,
        first.meetY - last.meetY);

    // Nominal period = travel time + hover budget at every cluster.
    m_nominalPeriod = totalDistance / vNominal + K * cfg.hoverBudget;
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
        }
        if (m.type == MsgType::DATA)
        {
            m_visit.readings += m.count;
        }
        else if (!m_planSent)
        {

            if (!m_neverContacted[m.cluster])
            {
                //m_lastStopsSincePromise[m.cluster] = static_cast<uint32_t>(m_totalArrivals >= m_arrivalsAtPromise[m.cluster] ? m_totalArrivals - m_arrivalsAtPromise[m.cluster]: 0);
                const uint64_t arrivalsSincePromise = m_totalArrivals - m_arrivalsAtPromise[m.cluster];

                m_lastStopsSincePromise[m.cluster] = static_cast<uint32_t>(arrivalsSincePromise > 0 ? arrivalsSincePromise - 1 : 0);

            }

            const double currentContactTime = m.contactTimeNs * 1e-9;
            const double currentBuffer = static_cast<double>(m.bufferAtContact);

            if (!m_neverContacted[m.cluster])
            {
                const double elapsed = currentContactTime - m_lastContactTime[m.cluster];

                if (elapsed > 0.0)
                {
                    const double observedRate = currentBuffer / elapsed;
                    constexpr double alpha = 0.3;

                    m_estimatedGenerationRate[m.cluster] = alpha * observedRate +(1.0 - alpha) * m_estimatedGenerationRate[m.cluster];
                }
            }

            m_lastContactBuffer[m.cluster] = currentBuffer;
            m_lastContactEnergy[m.cluster] = m.residualEnergy;
            m_lastContactTime[m.cluster] = currentContactTime;
            m_neverContacted[m.cluster] = false;

            // m_planSent = true;
            // if (m_w->cfg.wakeMode == "scheduled")
            // {
            //     // Promise the cluster's slot in the next lap of the committed timetable (D7).
            //     double eta = Slot(m.cluster, c.visits);
            //     m_promise[m.cluster] = eta;
            //     Msg plan;
            //     plan.type = MsgType::PLAN;
            //     plan.cluster = m.cluster;
            //     plan.timeNs = static_cast<int64_t>(eta * 1e9);
            //     plan.halfWidthNs = static_cast<int64_t>(m_w->cfg.wakeHalfWidth * 1e9);
            //     Address ch = InetSocketAddress(InetSocketAddress::ConvertFrom(from).GetIpv4(), CH_PORT);
            //     m_socket->SendTo(MakePacket(plan), 0, ch);
            // }
            m_planSent = true;

            // Common promise rule for every routing policy:
            // next expected contact = current contact time + nominal tour period.
            const double eta = currentContactTime + m_nominalPeriod;
            m_promise[m.cluster] = eta;
            m_arrivalsAtPromise[m.cluster] = m_totalArrivals;

            // Only scheduled wake mode needs to communicate the promise to the CH.
            if (m_w->cfg.wakeMode == "scheduled")
            {
                Msg plan;
                plan.type = MsgType::PLAN;
                plan.cluster = m.cluster;
                plan.timeNs = static_cast<int64_t>(eta * 1e9);
                plan.halfWidthNs = static_cast<int64_t>(m_w->cfg.wakeHalfWidth * 1e9);
                double lateMargin = m_w->cfg.adaptiveLateMargin;

                const auto it = m_latenessByStops.find(m_lastStopsSincePromise[m.cluster]);

                if (it != m_latenessByStops.end() && it->second.size() >= m_w->cfg.etaMinSamples)
                {
                    lateMargin = CalculateQuantile(it->second, m_w->cfg.etaQuantile);
                }

                plan.lateWidthNs = static_cast<int64_t>(lateMargin * 1e9);
                NS_LOG_UNCOND(
                "ETA ADAPTIVE: cluster=" << m.cluster
                << " stops=" << m_lastStopsSincePromise[m.cluster]
                << " samples=" << (it != m_latenessByStops.end() ? it->second.size() : 0)
                << " lateMargin=" << lateMargin);

                Address ch = InetSocketAddress(InetSocketAddress::ConvertFrom(from).GetIpv4(), CH_PORT);

                m_socket->SendTo(MakePacket(plan), 0, ch);
            }
            m_endEvent = Simulator::Schedule(Seconds(END_GUARD), &UavApp::EndHover, this);
        }
    }
}

} // namespace wsnuav
