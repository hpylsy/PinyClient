#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>

#include <opencv2/opencv.hpp>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <ament_index_cpp/get_package_share_directory.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <thread>

#include "doorlock_stream_e2e/config.hpp"
#include "doorlock_stream_e2e/packet_protocol.hpp"
#include "doorlock_stream_e2e/sniper_preprocessor.hpp"
#include "vision/detector/guide_light_detector.hpp"

using namespace doorlock_stream_e2e;

namespace {
std::atomic<bool> g_stop{false};

void signal_handler(int)
{
  g_stop.store(true);
}

bool parse_bool(const std::string & v, bool & out)
{
  if (v == "1" || v == "true" || v == "TRUE" || v == "on") {
    out = true;
    return true;
  }
  if (v == "0" || v == "false" || v == "FALSE" || v == "off") {
    out = false;
    return true;
  }
  return false;
}

void print_usage(const char * prog)
{
  std::cout
    << "Usage: " << prog << " [options]\n"
    << "  --mode file|camera          Source mode (default: file)\n"
    << "  --file PATH                 Input video file\n"
    << "  --camera DEVICE             Camera device (default: /dev/video0)\n"
    << "  --host IP                   Receiver IP (default: 127.0.0.1)\n"
    << "  --port N                    UDP port (default: 5600)\n"
    << "  --fps N                     Output fps (default: 50)\n"
    << "  --bitrate N                 x264 bitrate kbps (default: 300)\n"
    << "  --mtu N                     RTP payload mtu bytes (default: 300)\n"
    << "  --loop true|false           Loop file playback (default: true)\n"
    << "  --crop-size N               Center crop size (default: 800)\n"
    << "  --output-size N             Output size (default: 300)\n"
    << "  --enable-display true|false Show Raw/ROI/Static/Final windows (default: true)\n";
}

bool parse_args(int argc, char** argv, SenderConfig& cfg)
{
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    auto read_next = [&](std::string & out) -> bool {
      if (i + 1 >= argc) {
        return false;
      }
      out = argv[++i];
      return true;
    };

    if (arg == "--mode") {
      if (!read_next(cfg.mode)) return false;
    } else if (arg == "--file") {
      if (!read_next(cfg.file_path)) return false;
    } else if (arg == "--camera") {
      if (!read_next(cfg.camera_device)) return false;
    } else if (arg == "--host") {
      if (!read_next(cfg.host)) return false;
    } else if (arg == "--port") {
      std::string v;
      if (!read_next(v)) return false;
      cfg.port = std::stoi(v);
    } else if (arg == "--fps") {
      std::string v;
      if (!read_next(v)) return false;
      cfg.fps = std::stoi(v);
    } else if (arg == "--bitrate") {
      std::string v;
      if (!read_next(v)) return false;
      cfg.bitrate_kbps = std::stoi(v);
    } else if (arg == "--mtu") {
      std::string v;
      if (!read_next(v)) return false;
      cfg.mtu = std::stoi(v);
    } else if (arg == "--loop") {
      std::string v;
      if (!read_next(v) || !parse_bool(v, cfg.loop)) return false;
    } else if (arg == "--crop-size") {
      std::string v;
      if (!read_next(v)) return false;
      cfg.crop_size = std::stoi(v);
    } else if (arg == "--output-size") {
      std::string v;
      if (!read_next(v)) return false;
      cfg.output_size = std::stoi(v);
    } else if (arg == "--enable-display") {
      std::string v;
      if (!read_next(v) || !parse_bool(v, cfg.enable_display)) return false;
    } else if (arg == "-h" || arg == "--help") {
      print_usage(argv[0]);
      return false;
    } else {
      std::cerr << "Unknown argument: " << arg << "\n";
      return false;
    }
  }
  return true;
}



std::string build_pipeline(const SenderConfig & cfg)
{
  std::ostringstream ss;
  const int pay_mtu = std::max(1, cfg.mtu - 2);
  ss
    << "appsrc name=src is-live=true format=time do-timestamp=true "
    << "caps=video/x-raw,format=BGR,width=" << cfg.output_size
    << ",height=" << cfg.output_size << ",framerate=" << cfg.fps << "/1 ! "
    << "videoconvert ! "
    << "x264enc tune=zerolatency speed-preset=ultrafast bitrate=" << cfg.bitrate_kbps
    << " key-int-max=" << cfg.fps << " bframes=0 byte-stream=true aud=true ! "
    << "h264parse config-interval=1 ! "
    << "rtph264pay pt=96 mtu=" << pay_mtu << " config-interval=1 ! "
    << "appsink name=rtp_sink sync=false max-buffers=1000 drop=false emit-signals=false";
  return ss.str();
}

bool open_capture(const SenderConfig & cfg, cv::VideoCapture & cap)
{
  if (cfg.mode == "camera") {
    std::cout << "[sender] opening camera: " << cfg.camera_device << std::endl;
    cap.open(cfg.camera_device, cv::CAP_V4L2);
    cap.set(cv::CAP_PROP_FPS, static_cast<double>(cfg.fps));
    if (!cap.isOpened()) {
      std::cerr << "[sender][ERROR] failed to open camera: " << cfg.camera_device << std::endl;
      return false;
    }
    std::cout << "[sender] camera opened successfully" << std::endl;
    return true;
  }

  // File mode: check if file exists first
  std::ifstream check_file(cfg.file_path);
  if (!check_file.good()) {
    std::cerr << "[sender][ERROR] video file does not exist: " << cfg.file_path << std::endl;
    std::cerr << "[sender] suggestion: use absolute path or check file location" << std::endl;
    return false;
  }

  std::cout << "[sender] opening video file: " << cfg.file_path << std::endl;
  cap.open(cfg.file_path);
  if (!cap.isOpened()) {
    std::cerr << "[sender][ERROR] failed to open video file (check codec/format): " << cfg.file_path << std::endl;
    return false;
  }
  std::cout << "[sender] video file opened successfully" << std::endl;
  return true;
}

}  // namespace

int main(int argc, char ** argv)
{
  gst_init(&argc, &argv);
  std::signal(SIGINT, signal_handler);

  SenderConfig cfg;
  if (!parse_args(argc, argv, cfg)) {
    return 1;
  }

  std::string package_path;
  try {
    package_path = ament_index_cpp::get_package_share_directory("doorlock_stream_e2e");
  } catch (const std::exception &) {
    package_path = ".";
  }
  std::string model_path = package_path + "/models/light_320/best_openvino_model/best.xml";

  // Initialize neural detector for dynamic ROI guidance.
  rm_auto_aim::GuideLightDetector::LightParams detector_params;
  detector_params.use_nn = true;
  detector_params.nn_model_path = model_path;
  detector_params.nn_input_size = 320;
  detector_params.nn_conf_thres = 0.5;
  detector_params.nn_class_score_thres = 0.5;
  detector_params.nn_target_class_id = 0;
  rm_auto_aim::GuideLightDetector detector(detector_params);

  cv::VideoCapture cap;
  if (!open_capture(cfg, cap)) {
    std::cerr << "[sender][ERROR] failed to open source" << std::endl;
    return 2;
  }

  if (cfg.mode == "file") {
    const double src_fps = cap.get(cv::CAP_PROP_FPS);
    if (src_fps > 1.0 && cfg.fps <= 0) {
      cfg.fps = static_cast<int>(std::round(src_fps));
    }
  }
  if (cfg.fps <= 0) {
    cfg.fps = 50;
  }

  const std::string pipeline_desc = build_pipeline(cfg);
  std::cout << "[sender] pipeline: " << pipeline_desc << std::endl;
  std::cout << "[sender] config: fps=" << cfg.fps
            << " bitrate_kbps=" << cfg.bitrate_kbps
            << " mtu=" << cfg.mtu
            << " output_size=" << cfg.output_size
            << " crop_size=" << cfg.crop_size
            << std::endl;

  GError * error = nullptr;
  GstElement * pipeline = gst_parse_launch(pipeline_desc.c_str(), &error);
  if (!pipeline) {
    std::cerr << "[sender][ERROR] failed to create pipeline: "
              << (error ? error->message : "unknown") << std::endl;
    if (error) g_error_free(error);
    return 3;
  }

  GstElement * appsrc_elem = gst_bin_get_by_name(GST_BIN(pipeline), "src");
  if (!appsrc_elem) {
    std::cerr << "[sender][ERROR] cannot find appsrc element" << std::endl;
    gst_object_unref(pipeline);
    return 4;
  }

  GstBus * bus = gst_element_get_bus(pipeline);
  gst_element_set_state(pipeline, GST_STATE_PLAYING);

  int udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (udp_fd < 0) {
    std::cerr << "[sender][ERROR] failed to create UDP socket" << std::endl;
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(appsrc_elem);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    return 5;
  }

  sockaddr_in udp_target_addr;
  std::memset(&udp_target_addr, 0, sizeof(udp_target_addr));
  udp_target_addr.sin_family = AF_INET;
  udp_target_addr.sin_port = htons(static_cast<uint16_t>(cfg.port));
  if (inet_pton(AF_INET, cfg.host.c_str(), &udp_target_addr.sin_addr) != 1) {
    std::cerr << "[sender][ERROR] invalid UDP host IP: " << cfg.host << std::endl;
    close(udp_fd);
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(appsrc_elem);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    return 6;
  }
  std::cout << "[sender] udp target: " << cfg.host << ":" << cfg.port << std::endl;

  GstElement * rtp_sink = gst_bin_get_by_name(GST_BIN(pipeline), "rtp_sink");
  if (!rtp_sink) {
    std::cerr << "[sender][ERROR] cannot find appsink element rtp_sink" << std::endl;
    close(udp_fd);
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(appsrc_elem);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    return 7;
  }

  std::thread udp_sender_thread([&]() {
    while (!g_stop.load()) {
      GstSample * sample = gst_app_sink_try_pull_sample(
        GST_APP_SINK(rtp_sink),
        1 * GST_MSECOND);
      if (sample == nullptr) {
        continue;
      }

      GstBuffer * buffer = gst_sample_get_buffer(sample);
      if (buffer == nullptr) {
        gst_sample_unref(sample);
        continue;
      }

      GstMapInfo map;
      if (!gst_buffer_map(buffer, &map, GST_MAP_READ)) {
        gst_sample_unref(sample);
        continue;
      }

      const size_t actual_len = map.size;
      if (actual_len <= 298) {
        uint8_t payload[300] = {0};
        payload[0] = static_cast<uint8_t>(actual_len & 0xFF);
        payload[1] = static_cast<uint8_t>((actual_len >> 8) & 0xFF);
        std::memcpy(payload + 2, map.data, actual_len);

        sendto(
          udp_fd,
          payload,
          sizeof(payload),
          0,
          reinterpret_cast<const sockaddr *>(&udp_target_addr),
          sizeof(udp_target_addr));
      } else {
        std::cerr << "[sender][WARN] appsink packet too large: " << actual_len << " (> 298), dropped" << std::endl;
      }

      gst_buffer_unmap(buffer, &map);
      gst_sample_unref(sample);
    }
  });

  SniperPreprocessor pre(cfg);

  bool display_enabled = cfg.enable_display;
  if (display_enabled) {
    try {
      cv::namedWindow("Doorlock Sniper Raw", cv::WINDOW_NORMAL);
      cv::namedWindow("Doorlock Sniper ROI", cv::WINDOW_NORMAL);
      cv::namedWindow("Doorlock Sniper Static", cv::WINDOW_NORMAL);
      cv::namedWindow("Doorlock Sniper", cv::WINDOW_NORMAL);
      std::cout << "[sender] display windows initialized" << std::endl;
    } catch (const cv::Exception & e) {
      std::cerr << "[sender][WARN] failed to initialize display: " << e.what() << std::endl;
      std::cerr << "[sender] disabling display output (running in headless mode)" << std::endl;
      display_enabled = false;
    }
  }

  const auto frame_interval = std::chrono::nanoseconds(1000000000LL / std::max(cfg.fps, 1));
  auto next_tick = std::chrono::steady_clock::now();
  uint64_t frame_idx = 0;

  while (!g_stop.load()) {
    cv::Mat input;
    if (!cap.read(input) || input.empty()) {
      if (cfg.mode == "file" && cfg.loop) {
        cap.set(cv::CAP_PROP_POS_FRAMES, 0);
        if (!cap.read(input) || input.empty()) {
          std::cerr << "[sender][ERROR] loop read failed" << std::endl;
          break;
        }
      } else {
        std::cout << "[sender] EOS" << std::endl;
        break;
      }
    }

    std::optional<cv::Point2f> track_point = std::nullopt;
    std::vector<rm_auto_aim::Light> lights = detector.detect(input);
    if (!lights.empty()) {
      track_point = lights[0].center;
    }

    cv::Mat roi;
    cv::Mat static_removed;
    cv::Mat processed = pre.preprocess(input, &roi, &static_removed, track_point);

    if (display_enabled) {
      try {
        cv::Mat raw_preview;
        cv::resize(
          input,
          raw_preview,
          cv::Size(std::max(1, input.cols / 2), std::max(1, input.rows / 2)),
          0,
          0,
          cv::INTER_AREA);
        cv::imshow("Doorlock Sniper Raw", raw_preview);
        cv::imshow("Doorlock Sniper ROI", roi);
        cv::imshow("Doorlock Sniper Static", static_removed);
        cv::imshow("Doorlock Sniper", processed);
        if ((cv::waitKey(1) & 0xFF) == 'q') {
          g_stop.store(true);
        }
      } catch (const cv::Exception & e) {
        std::cerr << "[sender][WARN] display error, disabling: " << e.what() << std::endl;
        display_enabled = false;
      }
    }

    const size_t bytes = processed.total() * processed.elemSize();
    GstBuffer * buffer = gst_buffer_new_allocate(nullptr, bytes, nullptr);
    if (!buffer) {
      std::cerr << "[sender][ERROR] failed to alloc gst buffer" << std::endl;
      break;
    }

    GstMapInfo map;
    if (!gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
      gst_buffer_unref(buffer);
      std::cerr << "[sender][ERROR] failed to map gst buffer" << std::endl;
      break;
    }
    std::memcpy(map.data, processed.data, bytes);
    gst_buffer_unmap(buffer, &map);

    GST_BUFFER_PTS(buffer) = static_cast<GstClockTime>(frame_idx) * static_cast<GstClockTime>(frame_interval.count());
    GST_BUFFER_DURATION(buffer) = static_cast<GstClockTime>(frame_interval.count());

    const GstFlowReturn flow_ret = gst_app_src_push_buffer(GST_APP_SRC(appsrc_elem), buffer);
    if (flow_ret != GST_FLOW_OK) {
      std::cerr << "[sender][ERROR] appsrc push failed: " << flow_ret << std::endl;
      break;
    }

    frame_idx++;

    while (true) {
      GstMessage * msg = gst_bus_pop_filtered(
        bus,
        static_cast<GstMessageType>(GST_MESSAGE_ERROR | GST_MESSAGE_WARNING));
      if (!msg) {
        break;
      }
      if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_WARNING) {
        GError * err = nullptr;
        gchar * dbg = nullptr;
        gst_message_parse_warning(msg, &err, &dbg);
        std::cerr << "[sender][WARN] " << (err ? err->message : "unknown") << std::endl;
        if (dbg) std::cerr << "[sender][WARN] debug: " << dbg << std::endl;
        if (err) g_error_free(err);
        if (dbg) g_free(dbg);
      } else if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR) {
        GError * err = nullptr;
        gchar * dbg = nullptr;
        gst_message_parse_error(msg, &err, &dbg);
        std::cerr << "[sender][ERROR] " << (err ? err->message : "unknown") << std::endl;
        if (dbg) std::cerr << "[sender][ERROR] debug: " << dbg << std::endl;
        if (err) g_error_free(err);
        if (dbg) g_free(dbg);
        g_stop.store(true);
      }
      gst_message_unref(msg);
    }

    next_tick += frame_interval;
    std::this_thread::sleep_until(next_tick);
  }

  g_stop.store(true);
  if (udp_sender_thread.joinable()) {
    udp_sender_thread.join();
  }

  gst_app_src_end_of_stream(GST_APP_SRC(appsrc_elem));
  gst_element_set_state(pipeline, GST_STATE_NULL);

  if (cfg.enable_display) {
    cv::destroyWindow("Doorlock Sniper Raw");
    cv::destroyWindow("Doorlock Sniper ROI");
    cv::destroyWindow("Doorlock Sniper Static");
    cv::destroyWindow("Doorlock Sniper");
  }

  gst_object_unref(appsrc_elem);
  gst_object_unref(bus);
  if (rtp_sink) {
    gst_object_unref(rtp_sink);
  }
  gst_object_unref(pipeline);
  close(udp_fd);
  return 0;
}
