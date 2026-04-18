#pragma once

#include <string>

#include "doorlock_stream_e2e/core/frame_types.hpp"

namespace doorlock_stream_e2e {

class IFrameSink {
public:
  virtual ~IFrameSink() = default;

  virtual void on_frame(std::shared_ptr<const FrameResult> result) = 0;
  virtual void on_status(StreamStatus status, const std::string & msg = "") = 0;
};

}  // namespace doorlock_stream_e2e
