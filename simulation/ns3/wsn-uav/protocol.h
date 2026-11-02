// CH<->UAV application messages, carried over UDP on the simulated 802.11 link.
#ifndef WSN_UAV_PROTOCOL_H
#define WSN_UAV_PROTOCOL_H

#include "ns3/packet.h"

#include <cstdint>
#include <cstring>
#include <vector>

namespace wsnuav
{

constexpr uint16_t CH_PORT = 9000;
constexpr uint16_t UAV_PORT = 9001;

enum class MsgType : uint8_t
{
    POLL = 1, // UAV -> broadcast: "UAV is at meeting point of `cluster`"
    DATA = 2, // CH -> UAV: `count` readings (payload padded to count * readingBytes)
    DONE = 3, // CH -> UAV: upload finished, `count` = readings sent in this contact
    PLAN = 4, // UAV -> CH: next promised arrival `timeNs` and window half-width `halfWidthNs`
    HEARTBEAT = 5,
    CH_UPDATE = 6
};

struct Msg
{
    MsgType type;
    uint8_t pad[3] = {0, 0, 0};
    uint32_t cluster = 0;
    uint32_t count = 0;
    int64_t timeNs = 0;
    int64_t halfWidthNs = 0;
    uint32_t primaryId = 0;
};

inline ns3::Ptr<ns3::Packet>
MakePacket(const Msg& m, uint32_t extraBytes = 0)
{
    std::vector<uint8_t> buf(sizeof(Msg) + extraBytes, 0);
    std::memcpy(buf.data(), &m, sizeof(Msg));
    return ns3::Create<ns3::Packet>(buf.data(), buf.size());
}

inline bool
ParsePacket(ns3::Ptr<ns3::Packet> p, Msg& m)
{
    if (p->GetSize() < sizeof(Msg))
    {
        return false;
    }
    p->CopyData(reinterpret_cast<uint8_t*>(&m), sizeof(Msg));
    return true;
}

} // namespace wsnuav

#endif
