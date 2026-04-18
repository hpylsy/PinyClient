#pragma once

#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>

#include <opencv2/opencv.hpp>

#include "doorlock_stream_e2e/core/i_frame_sink.hpp"

namespace doorlock_stream_e2e {

class DebugDisplaySink : public IFrameSink {
public:
  void on_frame(std::shared_ptr<const FrameResult> result) override
  {
    if (!result || !result->image || result->image->empty()) {
      return;
    }

    cv::Mat frame = result->image->clone();

    std::ostringstream ss;
    ss.setf(std::ios::fixed);
    ss.precision(1);
    ss << "fps=" << result->decode_fps
       << " drop=" << result->dropped_packets
       << " ts=" << result->timestamp_ms;

    const cv::Point org(12, 24);
    cv::putText(
      frame,
      ss.str(),
      org + cv::Point(1, 1),
      cv::FONT_HERSHEY_SIMPLEX,
      0.6,
      cv::Scalar(0, 0, 0),
      2,
      cv::LINE_AA);
    cv::putText(
      frame,
      ss.str(),
      org,
      cv::FONT_HERSHEY_SIMPLEX,
      0.6,
      cv::Scalar(255, 255, 255),
      1,
      cv::LINE_AA);

    cv::imshow("Receiver Debug", frame);
    cv::waitKey(1);
  }

  void on_status(StreamStatus status, const std::string & msg = "") override
  {
    std::cout << "[DebugDisplaySink] status=" << status_to_string(status);
    if (!msg.empty()) {
      std::cout << " msg=" << msg;
    }
    std::cout << std::endl;
  }

private:
  static const char * status_to_string(StreamStatus status)
  {
    switch (status) {
      case StreamStatus::CONNECTING:
        return "CONNECTING";
      case StreamStatus::STREAMING:
        return "STREAMING";
      case StreamStatus::DISCONNECTED:
        return "DISCONNECTED";
      case StreamStatus::ERROR:
        return "ERROR";
      default:
        return "UNKNOWN";
    }
  }
};

}  // namespace doorlock_stream_e2e
