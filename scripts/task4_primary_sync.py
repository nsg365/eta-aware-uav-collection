from pathlib import Path

ROOT = Path("simulation/ns3/wsn-uav")

def patch(filename, old, new):
    path = ROOT / filename
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"Could not find expected code in {path}")
    path.write_text(text.replace(old, new, 1))
    print(f"Updated {path}")

# 1. Store the CH sensor ID.
patch(
    "ch-app.h",
    """    ClusterHeadApp(World* world,
               uint32_t cluster,
               ns3::Ptr<ns3::WifiPhy> phy,
               double phase,
               double clockOffset);""",
    """    ClusterHeadApp(World* world,
               uint32_t cluster,
               uint32_t sensorId,
               ns3::Ptr<ns3::WifiPhy> phy,
               double phase,
               double clockOffset);"""
)

patch(
    "ch-app.h",
    """    World* m_w;
    Cluster& m_c;""",
    """    World* m_w;
    Cluster& m_c;
    uint32_t m_sensorId;"""
)

patch(
    "ch-app.cc",
    """ClusterHeadApp::ClusterHeadApp(World* world,
                               uint32_t cluster,
                               Ptr<WifiPhy> phy,
                               double phase,
                               double clockOffset)
    : m_w(world),
      m_c(world->clusters.at(cluster)),
      m_phy(phy),""",
    """ClusterHeadApp::ClusterHeadApp(World* world,
                               uint32_t cluster,
                               uint32_t sensorId,
                               Ptr<WifiPhy> phy,
                               double phase,
                               double clockOffset)
    : m_w(world),
      m_c(world->clusters.at(cluster)),
      m_sensorId(sensorId),
      m_phy(phy),"""
)

# 2. Only the currently active primary should respond to UAV polls.
patch(
    "ch-app.cc",
    """        if (m.type == MsgType::POLL && !m_busy)""",
    """        if (m.type == MsgType::POLL &&
            !m_busy &&
            m_w->clusters[m_c.id].primary == m_sensorId)"""
)

# 3. Tag DATA and DONE with the sender's sensor ID.
patch(
    "ch-app.cc",
    """        m.type = MsgType::DATA;
        m.count = n;""",
    """        m.type = MsgType::DATA;
        m.count = n;
        m.primaryId = m_sensorId;"""
)

patch(
    "ch-app.cc",
    """    m.type = MsgType::DONE;
    m.count = static_cast<uint32_t>(m_contactSent);""",
    """    m.type = MsgType::DONE;
    m.count = static_cast<uint32_t>(m_contactSent);
    m.primaryId = m_sensorId;"""
)

# 4. Add UAV active-primary state and a synchronization method.
patch(
    "uav-app.h",
    """  public:
    UavApp(World* world,
       std::unique_ptr<RoutingPolicy> policy,
       ns3::Ptr<ns3::NormalRandomVariable> speed,
       ns3::Ptr<ns3::UniformRandomVariable> delay);

  private:""",
    """  public:
    UavApp(World* world,
       std::unique_ptr<RoutingPolicy> policy,
       ns3::Ptr<ns3::NormalRandomVariable> speed,
       ns3::Ptr<ns3::UniformRandomVariable> delay);

    void SetActivePrimary(uint32_t clusterId, uint32_t sensorId);

  private:"""
)

patch(
    "uav-app.h",
    """    std::vector<double> m_promise; // per cluster, promised next arrival (-1 none)""",
    """    std::vector<double> m_promise; // per cluster, promised next arrival (-1 none)
    std::vector<uint32_t> m_activePrimary; // active CH sensor ID per cluster"""
)

patch(
    "uav-app.cc",
    """      m_delay(delay),
      m_promise(world->clusters.size(), -1.0)
{
}""",
    """      m_delay(delay),
      m_promise(world->clusters.size(), -1.0)
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
}"""
)

# 5. Reject DATA/DONE from a non-active primary.
patch(
    "uav-app.cc",
    """        Cluster& c = m_w->clusters[m.cluster];
        if (m.type == MsgType::DATA)
        {
            c.delivered += m.count; // counted even if it arrives late, it reached the UAV
        }
        bool current = m_hovering && m.cluster == m_visit.cluster;""",
    """        Cluster& c = m_w->clusters[m.cluster];

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

        bool current = m_hovering && m.cluster == m_visit.cluster;"""
)

# 6. Keep the global UAV application pointer for promotion synchronization.
patch(
    "wsn-uav.cc",
    """std::map<uint32_t, Ptr<WifiNetDevice>> g_wifiDev;   // sensor id -> device (primaries, backups)""",
    """std::map<uint32_t, Ptr<WifiNetDevice>> g_wifiDev;   // sensor id -> device (primaries, backups)
Ptr<UavApp> g_uavApp;"""
)

# 7. Pass sensor ID to primary and promoted-backup CH applications.
patch(
    "wsn-uav.cc",
    """auto app = CreateObject<ClusterHeadApp>(&g_world, s.cluster, p, phase->GetValue(), clockDrift->GetValue());""",
    """auto app = CreateObject<ClusterHeadApp>(
                &g_world, s.cluster, s.id, p, phase->GetValue(), clockDrift->GetValue());"""
)

patch(
    "wsn-uav.cc",
    """                            &g_world,
                            c.id,
                            backupPhy,""",
    """                            &g_world,
                            c.id,
                            backupId,
                            backupPhy,"""
)

# 8. Notify the UAV when promotion succeeds.
patch(
    "wsn-uav.cc",
    """                        // Register the promoted backup as the active CH.
                        g_chApp[backupId] = promotedApp;

                        NS_LOG_INFO(""",
    """                        // Register the promoted backup as the active CH.
                        g_chApp[backupId] = promotedApp;

                        // Synchronize the UAV's active-primary record.
                        g_uavApp->SetActivePrimary(c.id, backupId);

                        NS_LOG_INFO("""
)

# 9. Retain the UAV app in the global pointer.
patch(
    "wsn-uav.cc",
    """    auto uav = CreateObject<UavApp>(&g_world, std::move(policy), speed, uavDelay);
    uavNode->AddApplication(uav);
    uav->SetStartTime(Seconds(0));
    uav->SetStopTime(Seconds(cfg.simTime));""",
    """    g_uavApp = CreateObject<UavApp>(&g_world, std::move(policy), speed, uavDelay);
    uavNode->AddApplication(g_uavApp);
    g_uavApp->SetStartTime(Seconds(0));
    g_uavApp->SetStopTime(Seconds(cfg.simTime));"""
)

print("Primary synchronization patch applied.")

