#include <gst/app/gstappsink.h>
#include <gst/gst.h>

#if __has_include(<cv_bridge/cv_bridge.hpp>)
#include <cv_bridge/cv_bridge.hpp>
#else
#include <cv_bridge/cv_bridge.h>
#endif

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

#include <string>
#include <sstream>

class GstReceiverNode : public rclcpp::Node
{
public:
  GstReceiverNode()
  : Node("gst_receiver_node")
  {
    port_ = this->declare_parameter<int>("port", 5600);
    jitter_latency_ms_ = this->declare_parameter<int>("jitter_latency", 5);
    output_topic_ = this->declare_parameter<std::string>("output_topic", "/gst/image_raw");
    frame_id_ = this->declare_parameter<std::string>("frame_id", "gst_receiver_optical_frame");

    pub_ = this->create_publisher<sensor_msgs::msg::Image>(output_topic_, rclcpp::SensorDataQoS());

    init_pipeline();
    timer_ = this->create_wall_timer(std::chrono::milliseconds(5), std::bind(&GstReceiverNode::poll_once, this));

    RCLCPP_INFO(
      this->get_logger(),
      "gst_receiver_node started. listen udp:%d jitter=%dms -> topic %s",
      port_, jitter_latency_ms_, output_topic_.c_str());
  }

  ~GstReceiverNode() override
  {
    if (sink_ != nullptr) {
      gst_object_unref(sink_);
      sink_ = nullptr;
    }
    if (bus_ != nullptr) {
      gst_object_unref(bus_);
      bus_ = nullptr;
    }
    if (pipeline_ != nullptr) {
      gst_element_set_state(pipeline_, GST_STATE_NULL);
      gst_object_unref(pipeline_);
      pipeline_ = nullptr;
    }
  }

private:
  void init_pipeline()
  {
    if (!gst_is_initialized()) {
      int argc = 0;
      char ** argv = nullptr;
      gst_init(&argc, &argv);
    }

    std::ostringstream ss;
    ss
      << "udpsrc port=" << port_
      << " caps=\"application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000\" ! "
      << "rtpjitterbuffer latency=" << jitter_latency_ms_ << " drop-on-latency=true do-lost=true ! "
      << "rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! "
      << "video/x-raw,format=BGR ! appsink name=sink sync=false max-buffers=1 drop=true emit-signals=false";

    GError * error = nullptr;
    pipeline_ = gst_parse_launch(ss.str().c_str(), &error);
    if (pipeline_ == nullptr) {
      RCLCPP_FATAL(this->get_logger(), "create pipeline failed: %s", error ? error->message : "unknown");
      if (error) {
        g_error_free(error);
      }
      throw std::runtime_error("gst parse failed");
    }

    sink_ = gst_bin_get_by_name(GST_BIN(pipeline_), "sink");
    bus_ = gst_element_get_bus(pipeline_);
    if (sink_ == nullptr || bus_ == nullptr) {
      throw std::runtime_error("gst sink or bus missing");
    }

    if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("gst play failed");
    }
  }

  void poll_once()
  {
    if (sink_ == nullptr) {
      return;
    }

    GstSample * sample = gst_app_sink_try_pull_sample(GST_APP_SINK(sink_), 1 * GST_MSECOND);
    if (sample == nullptr) {
      return;
    }

    GstBuffer * buffer = gst_sample_get_buffer(sample);
    GstCaps * caps = gst_sample_get_caps(sample);
    if (buffer == nullptr || caps == nullptr) {
      gst_sample_unref(sample);
      return;
    }

    const GstStructure * s = gst_caps_get_structure(caps, 0);
    int width = 0;
    int height = 0;
    if (!gst_structure_get_int(s, "width", &width) || !gst_structure_get_int(s, "height", &height)) {
      gst_sample_unref(sample);
      return;
    }

    GstMapInfo map;
    if (!gst_buffer_map(buffer, &map, GST_MAP_READ)) {
      gst_sample_unref(sample);
      return;
    }

    cv::Mat frame(height, width, CV_8UC3, static_cast<void *>(map.data));
    auto msg = cv_bridge::CvImage(std_msgs::msg::Header(), "bgr8", frame).toImageMsg();
    msg->header.stamp = this->now();
    msg->header.frame_id = frame_id_;
    pub_->publish(*msg);

    gst_buffer_unmap(buffer, &map);
    gst_sample_unref(sample);

    while (true) {
      GstMessage * m = gst_bus_pop_filtered(bus_, static_cast<GstMessageType>(GST_MESSAGE_WARNING | GST_MESSAGE_ERROR));
      if (m == nullptr) {
        break;
      }
      gst_message_unref(m);
    }
  }

  int port_ = 5600;
  int jitter_latency_ms_ = 5;
  std::string output_topic_;
  std::string frame_id_;

  GstElement * pipeline_ = nullptr;
  GstElement * sink_ = nullptr;
  GstBus * bus_ = nullptr;

  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<GstReceiverNode>());
  rclcpp::shutdown();
  return 0;
}
