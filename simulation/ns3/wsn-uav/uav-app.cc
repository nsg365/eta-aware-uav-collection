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

UavApp::UavApp(World* world,
               std::unique_ptr<RoutingPolicy> policy,
               Ptr<NormalRandomVariable> speed,
               Ptr<UniformRandomVariable> delay)
    : m_w(world),
      m_policy(std::move(policy)),
      m_speed(speed),
      m_delay(delay),
      m_promise(world->clusters.size(), -1.0),
      m_lateWidth(world->clusters.size(), world->cfg.adaptiveLateMargin),
      m_promiseFactor(world->clusters.size(), 1.0),
      m_lastContactBuffer(world->clusters.size(), 0.0),
      m_lastContactEnergy(world->clusters.size(), 0.0),
      m_lastContactTime(world->clusters.size(), -1.0),
      m_estimatedGenerationRate(world->clusters.size(), 0.0),
      m_missedMeetings(world->clusters.size(), 0),
      m_neverContacted(world->clusters.size(), true),
      m_arrivalsAtPromise(world->clusters.size(), 0),
      m_lastStopsSincePromise(world->clusters.size(), 0),
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
    CalculateNominalPeriod(m_mob->GetPosition());

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
    m_policy->OnEpisodeEnd(*m_w);
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
        if (m_promise[i] >= 0.0)
        {
            beliefs[i].lateQuantile =
                LatenessQuantile(static_cast<uint32_t>(m_totalArrivals - m_arrivalsAtPromise[i]));
        }
    }

    const uint32_t currentCluster =
        (m_totalArrivals == 0) ? UINT32_MAX : m_visit.cluster;

    uint32_t k = m_policy->Next(
        *m_w, beliefs,
        currentPosition.x, currentPosition.y,
        currentCluster,
        0.5 * m_nominalPeriod);

    m_promiseFactor[k] = m_policy->PromiseFactor();
    const Cluster& c = m_w->clusters[k];


    Vector from = m_mob->GetPosition();
    Vector to(c.meetX, c.meetY, cfg.uavAltitude);
    double d = CalculateDistance(from, to);
    double v = std::max(cfg.uavMinSpeed, m_speed->GetValue());
    double flightTime = d / v;

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


    if (m_visit.promisedEta >= 0.0)
    {
        const double lateness = Simulator::Now().GetSeconds() - m_visit.promisedEta;

        const uint64_t arrivalsSincePromise =
            m_totalArrivals - m_arrivalsAtPromise[m_visit.cluster];

        const uint32_t stopsSincePromise = static_cast<uint32_t>(arrivalsSincePromise);
        m_latenessByStops[stopsSincePromise].push_back(lateness);
    }
    m_totalArrivals++;
    c.visits++;
    m_hovering = true;
    m_contact = false;
    m_planSent = false;
    // Wait until the next valid listening window before polling.
    double hold = HoldFor(m_visit.promisedEta, Simulator::Now().GetSeconds(), m_lateWidth[m_visit.cluster]);

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

    // Contact timeout and hover cap count from the end of the hold.
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
    const Cluster& first = m_w->clusters[order[0]];

    totalDistance += std::hypot(
        first.meetX - depot.x,
        first.meetY - depot.y);

    // Middle legs: between consecutive clusters.
    for (size_t i = 1; i < K; ++i)
    {
        const Cluster& previous = m_w->clusters[order[i - 1]];
        const Cluster& current = m_w->clusters[order[i]];

        totalDistance += std::hypot(
            current.meetX - previous.meetX,
            current.meetY - previous.meetY);
    }

    // Final leg: from the last cluster back to the first.
    const Cluster& last = m_w->clusters[order[K - 1]];

    totalDistance += std::hypot(
        first.meetX - last.meetX,
        first.meetY - last.meetY);

    // Nominal period = travel time + hover budget at every cluster.
    m_nominalPeriod = totalDistance / vNominal + K * cfg.hoverBudget;
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

double
UavApp::LatenessQuantile(uint32_t stopsSincePromise) const
{
    double q = m_w->cfg.adaptiveLateMargin;
    const auto it = m_latenessByStops.find(stopsSincePromise);
    if (it != m_latenessByStops.end() && it->second.size() >= m_w->cfg.etaMinSamples)
    {
        q = CalculateQuantile(it->second, m_w->cfg.etaQuantile);
    }
    return std::max(0.0, q);
}

// How long to hold at the meeting point so the CH is listening (D8). An early UAV waits for the
// promised window [tau - w, tau + w]; a late one waits for the next retry window, which opens at
// tau + w + m * retryInterval for m = 1..maxMissedRetries and lasts retryListen. After the last
// retry the CH is back in DISCOVERY and no hold is needed.
double
UavApp::HoldFor(double promised, double now, double lateWidth) const
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

    double end = promised + lateWidth;
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

            if (!m_neverContacted[m.cluster])
            {

                const uint64_t arrivalsSincePromise = m_totalArrivals - m_arrivalsAtPromise[m.cluster];

                m_lastStopsSincePromise[m.cluster] = static_cast<uint32_t>(arrivalsSincePromise > 0 ? arrivalsSincePromise - 1 : 0);

            }

            const double currentContactTime = m.contactTimeNs * 1e-9;
            const double currentBuffer = static_cast<double>(m.bufferAtContact);

           if (m_neverContacted[m.cluster])
            {
                // First contact: buffers start empty at simulation time zero.
                if (currentContactTime > 0.0)
                {
                    m_estimatedGenerationRate[m.cluster] = currentBuffer / currentContactTime;
                }
            }
            else
            {
                // Subsequent contacts: update the estimate using EWMA.
                const double elapsed = currentContactTime - m_lastContactTime[m.cluster];

                if (elapsed > 0.0)
                {
                    const double observedRate = currentBuffer / elapsed;
                    constexpr double alpha = 0.3;

                    m_estimatedGenerationRate[m.cluster] = alpha * observedRate + (1.0 - alpha) * m_estimatedGenerationRate[m.cluster];
                }
            }

            m_lastContactBuffer[m.cluster] = currentBuffer;
            m_lastContactEnergy[m.cluster] = m.residualEnergy;
            m_lastContactTime[m.cluster] = currentContactTime;
            m_neverContacted[m.cluster] = false;
            m_planSent = true;

            // Promise the next tour period (scaled by the policy's promise factor, 1 for fixed
            // policies), including extra time for uncontacted clusters.
            const SimConfig& cfg = m_w->cfg;
            double surveyExtra = std::max(0.0, 0.5 * cfg.dutyPeriod - cfg.hoverBudget);

            double eta = Simulator::Now().GetSeconds() + END_GUARD +
                         m_promiseFactor[m.cluster] * m_period + m_uncontacted * surveyExtra;

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
                const double lateMargin = m_w->cfg.adaptiveWindow
                                              ? LatenessQuantile(m_lastStopsSincePromise[m.cluster])
                                              : m_w->cfg.wakeHalfWidth;

                plan.lateWidthNs = static_cast<int64_t>(lateMargin * 1e9);
                m_lateWidth[m.cluster] = plan.lateWidthNs * 1e-9;

                Address ch = InetSocketAddress(InetSocketAddress::ConvertFrom(from).GetIpv4(), CH_PORT);

                m_socket->SendTo(MakePacket(plan), 0, ch);
            }
            m_endEvent = Simulator::Schedule(Seconds(END_GUARD), &UavApp::EndHover, this);
        }
    }
}

} // namespace wsnuav
