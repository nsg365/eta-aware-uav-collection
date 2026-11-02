from pathlib import Path

path = Path("simulation/ns3/wsn-uav/wsn-uav.cc")
text = path.read_text()

def replace_once(old, new, description):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one match for {description}; found {count}. "
            "No file written."
        )
    text = text.replace(old, new, 1)

replace_once(
    "constexpr int64_t STREAM_CLOCK_DRIFT = 100004;\n",
    "constexpr int64_t STREAM_CLOCK_DRIFT = 100004;\n"
    "constexpr int64_t STREAM_CH_FAILURE = 100005;\n",
    "failure RNG stream"
)

replace_once(
    "Ptr<UniformRandomVariable> g_loss154;\n",
    "Ptr<UniformRandomVariable> g_loss154;\n"
    "Ptr<UniformRandomVariable> g_chFailureRv;\n",
    "failure RNG global"
)

replace_once(
    "        const Sensor& primary = g_world.sensors.at(c.primary);\n",
    """        Sensor& primaryForFailure = g_world.sensors.at(c.primary);

        // Inject primary CH failures according to an exponential hazard rate.
        // Convert the configured rate [1/s] into probability per check interval.
        const double failureProbability =
            1.0 - std::exp(-g_world.cfg.chFailureRate *
                           g_world.cfg.heartbeatInterval);

        if (primaryForFailure.alive &&
            g_world.cfg.chFailureRate > 0.0 &&
            g_chFailureRv->GetValue() < failureProbability)
        {
            primaryForFailure.alive = false;
            primaryForFailure.deathTime = now;

            if (auto app = g_chApp.find(primaryForFailure.id);
                app != g_chApp.end())
            {
                app->second->OnDeath();
            }

            NS_LOG_INFO(
                now << "s random primary failure injected for cluster "
                    << c.id << ", primary sensor " << primaryForFailure.id);
        }

        const Sensor& primary = primaryForFailure;
""",
    "primary failure injection"
)

replace_once(
    "    g_loss154 = CreateObject<UniformRandomVariable>();\n"
    "    g_loss154->SetStream(STREAM_LOSS154);\n",
    "    g_loss154 = CreateObject<UniformRandomVariable>();\n"
    "    g_loss154->SetStream(STREAM_LOSS154);\n"
    "    g_chFailureRv = CreateObject<UniformRandomVariable>();\n"
    "    g_chFailureRv->SetStream(STREAM_CH_FAILURE);\n",
    "failure RNG initialization"
)

path.write_text(text)
print(f"Patched {path}")

