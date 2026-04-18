#pragma once

#include <cstdint>
#include <cstring>
#include <vector>

namespace doorlock_stream_e2e {

/**
 * 固定 300 字节 UDP/MQTT 包协议
 * 
 * 格式：
 *   [0-1]   : actual_len (uint16_t, 小端序) - 有效 RTP 数据长度 (0-298)
 *   [2-299] : RTP 数据 + 零填充
 * 
 * 使用场景：
 *   - Sender: 编码的 H.264 RTP 数据 → 300 字节包 → UDP/MQTT
 *   - Receiver: MQTT/UDP 300 字节包 → 提取 RTP 数据 → 解码
 */
class FixedPacketProtocol {
public:
  static constexpr size_t PACKET_SIZE = 300;
  static constexpr size_t HEADER_SIZE = 2;
  static constexpr size_t MAX_PAYLOAD = PACKET_SIZE - HEADER_SIZE;  // 298

  /**
   * 序列化：将 RTP 数据打包成 300 字节包
   * @param data RTP 原始数据
   * @param size RTP 数据大小 (0-298)
   * @return 300 字节的包 (使用 std::vector<uint8_t>)
   */
  static std::vector<uint8_t> serialize(const uint8_t* data, size_t size) {
    if (size > MAX_PAYLOAD) {
      size = MAX_PAYLOAD;
    }
    std::vector<uint8_t> packet(PACKET_SIZE, 0);
    packet[0] = static_cast<uint8_t>(size & 0xFF);
    packet[1] = static_cast<uint8_t>((size >> 8) & 0xFF);
    if (size > 0 && data) {
      std::memcpy(packet.data() + HEADER_SIZE, data, size);
    }
    return packet;
  }

  /**
   * 反序列化：从 300 字节包提取 RTP 数据
   * @param packet 300 字节的包
   * @param packet_size 包大小 (应该是 300)
   * @return 提取的 RTP 数据 (已清理填充)
   */
  static std::vector<uint8_t> deserialize(const uint8_t* packet, size_t packet_size) {
    std::vector<uint8_t> data;
    if (packet_size != PACKET_SIZE || !packet) {
      return data;
    }

    const uint16_t actual_len = static_cast<uint16_t>(packet[0]) |
                                static_cast<uint16_t>(static_cast<uint16_t>(packet[1]) << 8);
    if (actual_len > MAX_PAYLOAD) {
      return data;
    }

    if (actual_len > 0) {
      data.resize(actual_len);
      std::memcpy(data.data(), packet + HEADER_SIZE, actual_len);
    }
    return data;
  }

  /**
   * 验证包有效性
   */
  static bool validate(const uint8_t* packet, size_t packet_size) {
    if (packet_size != PACKET_SIZE || !packet) {
      return false;
    }
    const uint16_t actual_len = static_cast<uint16_t>(packet[0]) |
                                static_cast<uint16_t>(static_cast<uint16_t>(packet[1]) << 8);
    return actual_len <= MAX_PAYLOAD;
  }

  /**
   * 获取包中的有效负载长度
   */
  static uint16_t get_length(const uint8_t* packet) {
    if (!packet) return 0;
    return static_cast<uint16_t>(packet[0]) |
           static_cast<uint16_t>(static_cast<uint16_t>(packet[1]) << 8);
  }
};

}  // namespace doorlock_stream_e2e
