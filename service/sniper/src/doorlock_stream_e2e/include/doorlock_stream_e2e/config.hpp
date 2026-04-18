#pragma once

#include <string>

namespace doorlock_stream_e2e {

/**
 * Sender 配置
 */
struct SenderConfig {
  std::string source_mode = "camera";
  std::string network_mode = "local";
  bool enable_debug_ui = true;

  std::string mode = "file";
  std::string file_path = "/home/hpy/pioneer/hero/source/8.mp4";
  std::string camera_device = "/dev/video0";
  std::string host = "127.0.0.1";
  int port = 12345;
  int fps = 50;
  int bitrate_kbps = 300;
  int mtu = 300;
  bool loop = true;

  // Sniper preprocessing parameters
  int crop_size = 800;
  int output_size = 300;
  bool enable_display = true;
  bool static_simplify = true;
  int motion_threshold = 14;
  int motion_erode_px = 2;
  int motion_dilate_px = 6;
  int motion_trail_frames = 15;
  double trail_disable_motion_ratio = 0.30;
  double bg_update_alpha = 0.01;
  double bg_blur_sigma = 1.8;
  int center_clear_size = 150;
  bool force_monochrome = false;
};

/**
 * MQTT Receiver 配置
 */
struct ReceiverConfig {
  std::string source_mode = "camera";
  std::string network_mode = "local";
  bool enable_debug_ui = true;

  std::string host = "127.0.0.1";
  int port = 1883;
  std::string topic = "CustomByteBlock";
  int display_scale = 2;
  bool enable_display = true;
};

}  // namespace doorlock_stream_e2e
