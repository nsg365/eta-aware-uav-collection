from pathlib import Path

path = Path("simulation/ns3/wsn-uav/ch-app.cc")
text = path.read_text()

old = """    m_c.buffer = 0;
    m_phy->SetOffMode();
"""

new = """    m_c.buffer = 0;

    // SetOffMode is invalid when the PHY is already sleeping or off.
    // Leave those states unchanged; the dead app has cancelled its events.
    if (!m_phy->IsStateSleep() && !m_phy->IsStateOff())
    {
        m_phy->SetOffMode();
    }
"""

if text.count(old) != 1:
    raise SystemExit("Expected OnDeath PHY shutdown snippet exactly once; no file written.")

path.write_text(text.replace(old, new, 1))
print(f"Patched {path}")

