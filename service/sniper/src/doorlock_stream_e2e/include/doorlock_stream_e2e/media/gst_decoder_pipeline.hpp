#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>

#include "doorlock_stream_e2e/config.hpp"
#include "doorlock_stream_e2e/core/i_frame_sink.hpp"

namespace doorlock_stream_e2e {

class GstDecoderPipeline {
public:
  GstDecoderPipeline();
  ~GstDecoderPipeline();

  void set_sink(std::shared_ptr<IFrameSink> sink);

  bool start(const ReceiverConfig & cfg);
  void stop();

private:
  void worker_loop();
  void notify_status(StreamStatus status, const std::string & msg = "");
  bool pop_packet_for(std::vector<uint8_t> & out, std::chrono::milliseconds timeout);
  bool pop_packet_now(std::vector<uint8_t> & out);
  void enqueue_packet(std::vector<uint8_t> pkt);

  ReceiverConfig cfg_{};
  std::shared_ptr<IFrameSink> sink_;
  std::mutex sink_mutex_;

  std::mutex queue_mutex_;
  std::condition_variable queue_cv_;
  std::queue<std::vector<uint8_t>> packet_queue_;

  std::thread worker_thread_;
  std::atomic<bool> stop_flag_{false};
  std::atomic<bool> running_{false};
  std::atomic<uint32_t> dropped_packets_{0};
};

}  // namespace doorlock_stream_e2e
