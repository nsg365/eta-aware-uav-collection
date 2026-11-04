// Primary cluster-head application: buffer upload to the UAV and Wi-Fi sleep/listen scheduling.
//
// Wake modes (SimConfig::wakeMode):
//   always_on  - Wi-Fi radio never sleeps (ablation A5).
//   duty_cycle - listen dutyListen every dutyPeriod, independent of the UAV (ablation A6).
//   scheduled  - start in DISCOVERY (= duty cycle); after each contact the UAV sends a PLAN
//                with a promised arrival time t*, and the CH sleeps until t* - w and listens
//                until t* + w. A window that closes without contact is a missed meeting;
//                the CH enters RETRY and schedules another contact attempt.
//                Retry exhaustion returns the CH to DISCOVERY.
#ifndef WSN_UAV_CH_APP_H
#define WSN_UAV_CH_APP_H

#include "protocol.h"
#include "world.h"

#include "ns3/application.h"
#include "ns3/socket.h"
#include "ns3/wifi-phy.h"

namespace wsnuav
{

class ClusterHeadApp : public ns3::Application
{
  public:
    ClusterHeadApp(World* world,
               uint32_t cluster,
               uint32_t sensorId,
               ns3::Ptr<ns3::WifiPhy> phy,
               double phase,
               double clockOffset);

    // Called by the energy check when the primary CH's battery is exhausted.
    void OnDeath();

  private:
    void StartApplication() override;
    void StopApplication() override;

    void Wake();
    void Sleep();
    void TrySleep();

    void EnterDiscovery(bool initial);
    void DiscoveryListen();
    void DiscoverySleep();

    void OpenWindow(double closeAt);
    void CloseWindow();

    // Scheduled-contact retry mechanism
    void ScheduleRetry();
    void RetryWindow();
    void RetryExhausted();

    void Receive(ns3::Ptr<ns3::Socket> socket);
    void SendNextFrame();
    void PlanTimeout();
    void AfterContact();

    World* m_w;
    Cluster& m_c;
    uint32_t m_sensorId;
    ns3::Ptr<ns3::WifiPhy> m_phy;
    ns3::Ptr<ns3::Socket> m_socket;
    ns3::Address m_uav;
    double m_phase;
    double m_clockOffset;

    bool m_dead = false;
    bool m_wantAwake = false;
    double m_awakeSince = 0;
    bool m_busy = false; // uploading or waiting for PLAN
    bool m_inWindow = false;
    double m_windowOpen = 0;
    uint64_t m_contactSent = 0;

    // Scheduled-contact retry state
    uint32_t m_missedRetries = 0;
    bool m_retryPending = false;
    double m_retryTime = 0.0;

    ns3::EventId m_cycleEvent;  // discovery / window open
    ns3::EventId m_windowClose;
    ns3::EventId m_sendEvent;
    ns3::EventId m_planTimeout;
    ns3::EventId m_retryEvent;
};

} // namespace wsnuav

#endif
