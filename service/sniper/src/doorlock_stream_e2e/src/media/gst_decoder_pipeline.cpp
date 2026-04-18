#include "doorlock_stream_e2e/media/gst_decoder_pipeline.hpp"

#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <gst/gst.h>

#include <mqtt/async_client.h>

#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>

namespace doorlock_stream_e2e {
namespace {

struct Telemetry {
  std::chrono::steady_clock::time_point last_frame_tp{};
  double fps = 0.0;
};

std::string build_pipeline()
{
  std::ostringstream ss;
  ss
    << "appsrc name=v_src is-live=true format=time do-timestamp=false "
    << "caps=\"application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000\" ! "
    << "rtpjitterbuffer latency=50 drop-on-latency=true ! "
    << "rtph264depay ! h264parse ! avdec_h264 ! "
    << "videoconvert ! video/x-raw,format=BGR ! "
    << "appsink name=sink sync=false max-buffers=5 drop=true emit-signals=false";
  return ss.str();
}

class MqttCallback : public virtual mqtt::callback {
public:
  MqttCallback(
    std::queue<std::vector<uint8_t>> & queue,
    std::mutex & queue_mutex,
    std::condition_variable & queue_cv,
    std::atomic<uint32_t> & dropped_packets)
  : queue_(queue),
    queue_mutex_(queue_mutex),
    queue_cv_(queue_cv),
    dropped_packets_(dropped_packets)
  {
  }

  void connection_lost(const std::string & cause) override
  {
    std::cerr << "[decoder][WARN] MQTT connection lost: " << cause << std::endl;
  }

  void message_arrived(mqtt::const_message_ptr msg) override
  {
    const auto & payload = msg->get_payload();
    const size_t raw_size = payload.size();
    if (raw_size != 300) {
      dropped_packets_.fetch_add(1, std::memory_order_relaxed);
      return;
    }

    const auto * bytes = reinterpret_cast<const uint8_t *>(payload.data());
    const uint16_t actual_len = static_cast<uint16_t>(bytes[0]) |
      static_cast<uint16_t>(static_cast<uint16_t>(bytes[1]) << 8);
    if (actual_len > 298) {
      dropped_packets_.fetch_add(1, std::memory_order_relaxed);
      return;
    }

    if (actual_len == 0) {
      return;
    }

    std::vector<uint8_t> clean_payload(actual_len);
    std::memcpy(clean_payload.data(), bytes + 2, actual_len);
    {
      std::lock_guard<std::mutex> lk(queue_mutex_);
      queue_.push(std::move(clean_payload));
    }
    queue_cv_.notify_one();
  }

  void delivery_complete(mqtt::delivery_token_ptr) override {}

private:
  std::queue<std::vector<uint8_t>> & queue_;
  std::mutex & queue_mutex_;
  std::condition_variable & queue_cv_;
  std::atomic<uint32_t> & dropped_packets_;
};

}  // namespace

GstDecoderPipeline::GstDecoderPipeline() = default;

GstDecoderPipeline::~GstDecoderPipeline()
{
  stop();
}

void GstDecoderPipeline::set_sink(std::shared_ptr<IFrameSink> sink)
{
  std::lock_guard<std::mutex> lk(sink_mutex_);
  sink_ = std::move(sink);
}

bool GstDecoderPipeline::start(const ReceiverConfig & cfg)
{
  if (running_.load(std::memory_order_relaxed)) {
    return false;
  }

  cfg_ = cfg;
  stop_flag_.store(false, std::memory_order_relaxed);
  dropped_packets_.store(0, std::memory_order_relaxed);
  {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    std::queue<std::vector<uint8_t>> empty;
    packet_queue_.swap(empty);
  }

  running_.store(true, std::memory_order_relaxed);
  worker_thread_ = std::thread([this]() { worker_loop(); });
  return true;
}

void GstDecoderPipeline::stop()
{
  stop_flag_.store(true, std::memory_order_relaxed);
  queue_cv_.notify_all();
  if (worker_thread_.joinable()) {
    worker_thread_.join();
  }
}

void GstDecoderPipeline::notify_status(StreamStatus status, const std::string & msg)
{
  std::shared_ptr<IFrameSink> local_sink;
  {
    std::lock_guard<std::mutex> lk(sink_mutex_);
    local_sink = sink_;
  }
  if (local_sink) {
    local_sink->on_status(status, msg);
  }
}

void GstDecoderPipeline::enqueue_packet(std::vector<uint8_t> pkt)
{
  {
    std::lock_guard<std::mutex> lk(queue_mutex_);
    packet_queue_.push(std::move(pkt));
  }
  queue_cv_.notify_one();
}

bool GstDecoderPipeline::pop_packet_for(std::vector<uint8_t> & out, std::chrono::milliseconds timeout)
{
  std::unique_lock<std::mutex> lk(queue_mutex_);
  if (!queue_cv_.wait_for(lk, timeout, [&]() {
      return !packet_queue_.empty() || stop_flag_.load(std::memory_order_relaxed);
    })) {
    return false;
  }

  if (packet_queue_.empty()) {
    return false;
  }

  out = std::move(packet_queue_.front());
  packet_queue_.pop();
  return true;
}

bool GstDecoderPipeline::pop_packet_now(std::vector<uint8_t> & out)
{
  std::lock_guard<std::mutex> lk(queue_mutex_);
  if (packet_queue_.empty()) {
    return false;
  }

  out = std::move(packet_queue_.front());
  packet_queue_.pop();
  return true;
}

void GstDecoderPipeline::worker_loop()
{
  notify_status(StreamStatus::CONNECTING, "decoder starting");

  int argc = 0;
  char ** argv = nullptr;
  gst_init(&argc, &argv);

  const std::string pipeline_desc = build_pipeline();
  GError * error = nullptr;
  GstElement * pipeline = gst_parse_launch(pipeline_desc.c_str(), &error);
  if (pipeline == nullptr) {
    const std::string msg = error != nullptr ? error->message : "failed to create pipeline";
    if (error != nullptr) {
      g_error_free(error);
    }
    notify_status(StreamStatus::ERROR, msg);
    running_.store(false, std::memory_order_relaxed);
    return;
  }

  GstElement * appsrc_elem = gst_bin_get_by_name(GST_BIN(pipeline), "v_src");
  GstElement * sink_elem = gst_bin_get_by_name(GST_BIN(pipeline), "sink");
  GstBus * bus = gst_element_get_bus(pipeline);
  if (appsrc_elem == nullptr || sink_elem == nullptr || bus == nullptr) {
    notify_status(StreamStatus::ERROR, "failed to get appsrc/appsink/bus");
    if (appsrc_elem != nullptr) {
      gst_object_unref(appsrc_elem);
    }
    if (sink_elem != nullptr) {
      gst_object_unref(sink_elem);
    }
    if (bus != nullptr) {
      gst_object_unref(bus);
    }
    gst_object_unref(pipeline);
    running_.store(false, std::memory_order_relaxed);
    return;
  }

  gst_element_set_state(pipeline, GST_STATE_PLAYING);

  const std::string server_uri = "tcp://" + cfg_.host + ":" + std::to_string(cfg_.port);
  mqtt::async_client client(server_uri, "gst_decoder_pipeline_client");
  MqttCallback callback(packet_queue_, queue_mutex_, queue_cv_, dropped_packets_);
  client.set_callback(callback);

  mqtt::connect_options conn_opts;
  conn_opts.set_clean_session(true);
  conn_opts.set_automatic_reconnect(true);

  try {
    client.connect(conn_opts)->wait();
    client.subscribe(cfg_.topic, 0)->wait();
  } catch (const mqtt::exception & e) {
    notify_status(StreamStatus::ERROR, e.what());
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(appsrc_elem);
    gst_object_unref(sink_elem);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    running_.store(false, std::memory_order_relaxed);
    return;
  }

  notify_status(StreamStatus::STREAMING, "decoder streaming");

  Telemetry telemetry;

  while (!stop_flag_.load(std::memory_order_relaxed)) {
    std::vector<uint8_t> pkt;
    if (pop_packet_for(pkt, std::chrono::milliseconds(2))) {
      auto push_packet = [&](const std::vector<uint8_t> & p) {
          GstBuffer * buffer = gst_buffer_new_allocate(nullptr, p.size(), nullptr);
          if (buffer != nullptr) {
            GstMapInfo map;
            if (gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
              if (!p.empty()) {
                std::memcpy(map.data, p.data(), p.size());
              }
              gst_buffer_unmap(buffer, &map);
              const GstFlowReturn flow_ret = gst_app_src_push_buffer(GST_APP_SRC(appsrc_elem), buffer);
              if (flow_ret != GST_FLOW_OK) {
                notify_status(StreamStatus::ERROR, "appsrc push failed");
                stop_flag_.store(true, std::memory_order_relaxed);
              }
            } else {
              gst_buffer_unref(buffer);
            }
          }
        };

      push_packet(pkt);
      while (pop_packet_now(pkt)) {
        push_packet(pkt);
      }
    }

    while (true) {
      GstMessage * msg = gst_bus_pop_filtered(
        bus,
        static_cast<GstMessageType>(GST_MESSAGE_ERROR | GST_MESSAGE_WARNING | GST_MESSAGE_EOS));
      if (msg == nullptr) {
        break;
      }

      if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR) {
        GError * err = nullptr;
        gchar * dbg = nullptr;
        gst_message_parse_error(msg, &err, &dbg);
        const std::string err_msg = err != nullptr ? err->message : "gstreamer error";
        if (err != nullptr) {
          g_error_free(err);
        }
        if (dbg != nullptr) {
          g_free(dbg);
        }
        notify_status(StreamStatus::ERROR, err_msg);
        stop_flag_.store(true, std::memory_order_relaxed);
      } else if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_EOS) {
        notify_status(StreamStatus::DISCONNECTED, "gstreamer eos");
        stop_flag_.store(true, std::memory_order_relaxed);
      }

      gst_message_unref(msg);
    }

    GstSample * sample = gst_app_sink_try_pull_sample(GST_APP_SINK(sink_elem), 0);
    if (sample == nullptr) {
      continue;
    }

    GstBuffer * sample_buffer = gst_sample_get_buffer(sample);
    GstCaps * sample_caps = gst_sample_get_caps(sample);
    if (sample_buffer == nullptr || sample_caps == nullptr) {
      gst_sample_unref(sample);
      continue;
    }

    const GstStructure * caps_struct = gst_caps_get_structure(sample_caps, 0);
    int width = 0;
    int height = 0;
    if (!gst_structure_get_int(caps_struct, "width", &width) ||
      !gst_structure_get_int(caps_struct, "height", &height)) {
      gst_sample_unref(sample);
      continue;
    }

    GstMapInfo sample_map;
    if (!gst_buffer_map(sample_buffer, &sample_map, GST_MAP_READ)) {
      gst_sample_unref(sample);
      continue;
    }

    cv::Mat raw(height, width, CV_8UC3, static_cast<void *>(sample_map.data));
    cv::Mat frame = raw.clone();

    const auto now = std::chrono::steady_clock::now();
    if (telemetry.last_frame_tp.time_since_epoch().count() != 0) {
      const double period_ms = std::chrono::duration<double, std::milli>(now - telemetry.last_frame_tp).count();
      if (period_ms > 0.0) {
        telemetry.fps = 1000.0 / period_ms;
      }
    }
    telemetry.last_frame_tp = now;

    auto frame_result = std::make_shared<FrameResult>();
    frame_result->image = std::make_shared<const cv::Mat>(std::move(frame));
    frame_result->timestamp_ms = static_cast<uint64_t>(
      std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count());
    frame_result->decode_fps = telemetry.fps;
    frame_result->dropped_packets = dropped_packets_.load(std::memory_order_relaxed);

    gst_buffer_unmap(sample_buffer, &sample_map);
    gst_sample_unref(sample);

    std::shared_ptr<IFrameSink> local_sink;
    {
      std::lock_guard<std::mutex> lk(sink_mutex_);
      local_sink = sink_;
    }
    if (local_sink) {
      local_sink->on_frame(frame_result);
    }
  }

  try {
    if (client.is_connected()) {
      client.unsubscribe(cfg_.topic)->wait();
      client.disconnect()->wait();
    }
  } catch (const mqtt::exception & e) {
    notify_status(StreamStatus::ERROR, e.what());
  }

  gst_app_src_end_of_stream(GST_APP_SRC(appsrc_elem));
  gst_element_set_state(pipeline, GST_STATE_NULL);

  gst_object_unref(appsrc_elem);
  gst_object_unref(sink_elem);
  gst_object_unref(bus);
  gst_object_unref(pipeline);

  notify_status(StreamStatus::DISCONNECTED, "decoder stopped");
  running_.store(false, std::memory_order_relaxed);
}

}  // namespace doorlock_stream_e2e
