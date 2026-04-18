#pragma once

#include <cstdint>
#include <memory>
#include <opencv2/opencv.hpp>
#include <string>

namespace doorlock_stream_e2e {

enum class StreamStatus {
  CONNECTING,
  STREAMING,
  DISCONNECTED,
  ERROR,
};

struct FrameResult {
  std::shared_ptr<const cv::Mat> image;
  uint64_t timestamp_ms = 0;
  double decode_fps = 0.0;
  uint32_t dropped_packets = 0;
};

}  // namespace doorlock_stream_e2e
