#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <string>
#include <thread>

#include "doorlock_stream_e2e/config.hpp"
#include "doorlock_stream_e2e/media/gst_decoder_pipeline.hpp"
#include "doorlock_stream_e2e/sinks/debug_display_sink.hpp"

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
    << "  --host HOST                     MQTT host\n"
    << "  --port PORT                     MQTT port\n"
    << "  --topic TOPIC                   MQTT topic\n"
    << "  --display-scale N               Display scale\n"
    << "  --enable-display true|false     Backward-compatible alias of --enable-debug-ui\n"
    << "  --enable-debug-ui true|false    Enable local OpenCV debug sink\n"
    << "  --source-mode camera|file       Unified source mode switch\n"
    << "  --network-mode local|official   Unified network mode switch\n";
}

bool parse_args(int argc, char ** argv, ReceiverConfig & cfg)
{
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);

    auto next_value = [&](std::string & out) -> bool {
        if (i + 1 >= argc) {
          return false;
        }
        out = argv[++i];
        return true;
      };

    if (arg == "--host") {
      std::string v;
      if (!next_value(v)) return false;
      cfg.host = v;
    } else if (arg == "--port") {
      std::string v;
      if (!next_value(v)) return false;
      cfg.port = std::stoi(v);
    } else if (arg == "--topic") {
      std::string v;
      if (!next_value(v)) return false;
      cfg.topic = v;
    } else if (arg == "--display-scale") {
      std::string v;
      if (!next_value(v)) return false;
      cfg.display_scale = std::max(1, std::stoi(v));
    } else if (arg == "--enable-display") {
      std::string v;
      if (!next_value(v) || !parse_bool(v, cfg.enable_debug_ui)) return false;
      cfg.enable_display = cfg.enable_debug_ui;
    } else if (arg == "--enable-debug-ui") {
      std::string v;
      if (!next_value(v) || !parse_bool(v, cfg.enable_debug_ui)) return false;
      cfg.enable_display = cfg.enable_debug_ui;
    } else if (arg == "--source-mode") {
      std::string v;
      if (!next_value(v)) return false;
      cfg.source_mode = v;
    } else if (arg == "--network-mode") {
      std::string v;
      if (!next_value(v)) return false;
      cfg.network_mode = v;
    } else if (arg == "-h" || arg == "--help") {
      print_usage(argv[0]);
      return false;
    } else {
      std::cerr << "Unknown argument: " << arg << std::endl;
      return false;
    }
  }
  return true;
}

}  // namespace

int main(int argc, char ** argv)
{
  std::signal(SIGINT, signal_handler);
  std::signal(SIGTERM, signal_handler);

  ReceiverConfig cfg;
  if (!parse_args(argc, argv, cfg)) {
    return 1;
  }

  GstDecoderPipeline decoder;
  if (cfg.enable_debug_ui) {
    decoder.set_sink(std::make_shared<DebugDisplaySink>());
  }

  if (!decoder.start(cfg)) {
    std::cerr << "[mqtt_receiver][ERROR] failed to start decoder" << std::endl;
    return 2;
  }

  while (!g_stop.load()) {
    std::this_thread::sleep_for(std::chrono::seconds(1));
  }

  decoder.stop();
  return 0;
}
