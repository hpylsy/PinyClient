#include <mqtt/async_client.h>

#include <arpa/inet.h>
#include <csignal>
#include <atomic>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <errno.h>
#include <iostream>
#include <string>

#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace
{
  std::atomic<bool> g_stop{false};

  constexpr int kUdpListenPort = 12345;
  constexpr size_t kPacketSize = 300;
  // [官方环境约束]
  // Broker 固定为 192.168.12.1:3333（RoboMaster 2026 协议文档）。
  constexpr const char *kMqttServer = "tcp://192.168.12.1:3333";
  // [身份约束]
  // client_id 必须使用官方允许的选手端编号字符串（如红方英雄 0x0101 的十进制字符串 1）。
  // 当前值用于联调，请按赛场分配规则替换，避免与在线客户端身份冲突。
  constexpr const char *kMqttClientId = "2";
  constexpr const char *kMqttTopic = "CustomByteBlock";
  constexpr int kMqttQos = 0;

  void signal_handler(int)
  {
    g_stop.store(true);
  }

} // namespace

int main()
{
  std::signal(SIGINT, signal_handler);

  mqtt::async_client mqtt_client(kMqttServer, kMqttClientId);
  mqtt::connect_options conn_opts;
  conn_opts.set_clean_session(true);
  conn_opts.set_automatic_reconnect(true);

  try
  {
    std::cout << "[Mock Gateway] Connecting MQTT: " << kMqttServer << std::endl;
    mqtt_client.connect(conn_opts)->wait();
    std::cout << "[Mock Gateway] MQTT connected, topic=" << kMqttTopic << std::endl;
  }
  catch (const mqtt::exception &e)
  {
    std::cerr << "[Mock Gateway][ERROR] MQTT connect failed: " << e.what() << std::endl;
    return 1;
  }

  const int udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (udp_fd < 0)
  {
    std::cerr << "[Mock Gateway][ERROR] socket() failed: " << std::strerror(errno) << std::endl;
    try
    {
      if (mqtt_client.is_connected())
      {
        mqtt_client.disconnect()->wait();
      }
    }
    catch (const mqtt::exception &)
    {
    }
    return 2;
  }

  int reuse_addr = 1;
  if (setsockopt(udp_fd, SOL_SOCKET, SO_REUSEADDR, &reuse_addr, sizeof(reuse_addr)) != 0)
  {
    std::cerr << "[Mock Gateway][WARN] setsockopt(SO_REUSEADDR) failed: "
              << std::strerror(errno) << std::endl;
  }

  sockaddr_in listen_addr;
  std::memset(&listen_addr, 0, sizeof(listen_addr));
  listen_addr.sin_family = AF_INET;
  listen_addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  listen_addr.sin_port = htons(kUdpListenPort);

  if (bind(udp_fd, reinterpret_cast<const sockaddr *>(&listen_addr), sizeof(listen_addr)) != 0)
  {
    std::cerr << "[Mock Gateway][ERROR] bind(udp:" << kUdpListenPort << ") failed: "
              << std::strerror(errno) << std::endl;
    close(udp_fd);
    try
    {
      if (mqtt_client.is_connected())
      {
        mqtt_client.disconnect()->wait();
      }
    }
    catch (const mqtt::exception &)
    {
    }
    return 3;
  }

  std::cout << "[Mock Gateway] UDP listening on 127.0.0.1:" << kUdpListenPort << std::endl;

  std::array<uint8_t, kPacketSize> packet{};
  uint64_t forwarded_total = 0;
  uint64_t forwarded_since_log = 0;
  auto last_log_tp = std::chrono::steady_clock::now();

  while (!g_stop.load())
  {
    sockaddr_in src_addr;
    socklen_t src_len = sizeof(src_addr);
    const ssize_t n = recvfrom(
        udp_fd,
        packet.data(),
        packet.size(),
        0,
        reinterpret_cast<sockaddr *>(&src_addr),
        &src_len);

    if (n < 0)
    {
      if (errno == EINTR && g_stop.load())
      {
        break;
      }
      if (errno == EINTR)
      {
        continue;
      }
      std::cerr << "[Mock Gateway][WARN] recvfrom failed: " << std::strerror(errno) << std::endl;
      continue;
    }

    if (static_cast<size_t>(n) != kPacketSize)
    {
      continue;
    }

    try
    {
      auto msg = mqtt::make_message(
          kMqttTopic,
          reinterpret_cast<const void *>(packet.data()),
          packet.size());
      msg->set_qos(kMqttQos);
      msg->set_retained(false);
      mqtt_client.publish(msg);
    }
    catch (const mqtt::exception &e)
    {
      std::cerr << "[Mock Gateway][ERROR] MQTT publish failed: " << e.what() << std::endl;
      break;
    }

    ++forwarded_total;
    ++forwarded_since_log;

    const auto now = std::chrono::steady_clock::now();
    const bool hit_batch = (forwarded_since_log >= 50);
    const bool hit_interval =
        (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_log_tp).count() >= 1000);

    if (hit_batch || hit_interval)
    {
      std::cout << "[Mock Gateway] Forwarded " << forwarded_total
                << " packets to MQTT..." << std::endl;
      forwarded_since_log = 0;
      last_log_tp = now;
    }
  }

  close(udp_fd);

  try
  {
    if (mqtt_client.is_connected())
    {
      mqtt_client.disconnect()->wait();
      std::cout << "[Mock Gateway] MQTT disconnected" << std::endl;
    }
  }
  catch (const mqtt::exception &e)
  {
    std::cerr << "[Mock Gateway][WARN] MQTT disconnect failed: " << e.what() << std::endl;
  }

  std::cout << "[Mock Gateway] Stopped" << std::endl;
  return 0;
}
