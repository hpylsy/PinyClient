#include <gst/app/gstappsrc.h>
#include <gst/gst.h>

#if __has_include(<cv_bridge/cv_bridge.hpp>)
#include <cv_bridge/cv_bridge.hpp>
#else
#include <cv_bridge/cv_bridge.h>
#endif

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

#include <cstring>
#include <string>
#include <sstream>

class GstSenderNode : public rclcpp::Node
{
public:
  GstSenderNode()
  : Node("gst_sender_node")
  {
    input_topic_ = this->declare_parameter<std::string>("input_topic", "/image_raw");
    host_ = this->declare_parameter<std::string>("host", "127.0.0.1");
    port_ = this->declare_parameter<int>("port", 5600);
    fps_ = this->declare_parameter<int>("fps", 50);
    bitrate_kbps_ = this->declare_parameter<int>("bitrate", 300);
    mtu_ = this->declare_parameter<int>("mtu", 300);
    out_width_ = this->declare_parameter<int>("width", 300);
    out_height_ = this->declare_parameter<int>("height", 300);

    frame_duration_ns_ = static_cast<GstClockTime>(1000000000LL / std::max(1, fps_));
    init_pipeline();

    sub_ = this->create_subscription<sensor_msgs::msg::Image>(
      input_topic_, rclcpp::SensorDataQoS(),
      std::bind(&GstSenderNode::on_image, this, std::placeholders::_1));

    RCLCPP_INFO(
      this->get_logger(),
      "gst_sender_node started. input=%s -> %s:%d fps=%d packet_mtu=%d output=%dx%d bitrate=%dkbps",
      input_topic_.c_str(), host_.c_str(), port_, fps_, mtu_, out_width_, out_height_, bitrate_kbps_);
  }

  ~GstSenderNode() override
  {
    if (appsrc_ != nullptr) {
      gst_app_src_end_of_stream(GST_APP_SRC(appsrc_));
      gst_object_unref(appsrc_);
      appsrc_ = nullptr;
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
      << "appsrc name=src is-live=true format=time do-timestamp=true "
      << "caps=video/x-raw,format=BGR,width=" << out_width_
      << ",height=" << out_height_ << ",framerate=" << fps_ << "/1 ! "
      << "videoconvert ! "
      << "x264enc tune=zerolatency speed-preset=ultrafast bitrate=" << bitrate_kbps_
      << " key-int-max=" << fps_ << " bframes=0 byte-stream=true aud=true ! "
      << "h264parse config-interval=-1 ! "
      << "rtph264pay pt=96 mtu=" << mtu_ << " config-interval=1 ! "
      << "udpsink host=" << host_ << " port=" << port_ << " sync=false async=false";

    GError * error = nullptr;
    pipeline_ = gst_parse_launch(ss.str().c_str(), &error);
    if (pipeline_ == nullptr) {
      RCLCPP_FATAL(this->get_logger(), "create pipeline failed: %s", error ? error->message : "unknown");
      if (error) {
        g_error_free(error);
      }
      throw std::runtime_error("gst parse failed");
    }

    appsrc_ = gst_bin_get_by_name(GST_BIN(pipeline_), "src");
    bus_ = gst_element_get_bus(pipeline_);
    if (appsrc_ == nullptr || bus_ == nullptr) {
      throw std::runtime_error("gst element missing");
    }

    if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("gst play failed");
    }
  }

  void on_image(const sensor_msgs::msg::Image::SharedPtr msg)
  {
    if (appsrc_ == nullptr) {
      return;
    }

    cv_bridge::CvImageConstPtr cv_ptr;
    try {
      cv_ptr = cv_bridge::toCvShare(msg, "bgr8");
    } catch (const cv_bridge::Exception & e) {
      RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 2000, "cv_bridge: %s", e.what());
      return;
    }

    cv::Mat frame = cv_ptr->image;
    if (frame.empty()) {
      return;
    }

    cv::Mat out;
    if (frame.cols != out_width_ || frame.rows != out_height_) {
      cv::resize(frame, out, cv::Size(out_width_, out_height_), 0, 0, cv::INTER_LINEAR);
    } else {
      out = frame;
    }

    const size_t bytes = out.total() * out.elemSize();
    GstBuffer * buffer = gst_buffer_new_allocate(nullptr, bytes, nullptr);
    if (buffer == nullptr) {
      return;
    }

    GstMapInfo map;
    if (!gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
      gst_buffer_unref(buffer);
      return;
    }

    std::memcpy(map.data, out.data, bytes);
    gst_buffer_unmap(buffer, &map);

    GST_BUFFER_PTS(buffer) = frame_idx_ * frame_duration_ns_;
    GST_BUFFER_DURATION(buffer) = frame_duration_ns_;
    frame_idx_++;

    const GstFlowReturn flow_ret = gst_app_src_push_buffer(GST_APP_SRC(appsrc_), buffer);
    if (flow_ret != GST_FLOW_OK) {
      RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 1000, "appsrc push failed: %d", static_cast<int>(flow_ret));
    }

    while (true) {
      GstMessage * m = gst_bus_pop_filtered(bus_, static_cast<GstMessageType>(GST_MESSAGE_WARNING | GST_MESSAGE_ERROR));
      if (m == nullptr) {
        break;
      }
      gst_message_unref(m);
    }
  }

  std::string input_topic_;
  std::string host_;
  int port_ = 5600;
  int fps_ = 50;
  int bitrate_kbps_ = 300;
  int mtu_ = 300;
  int out_width_ = 300;
  int out_height_ = 300;

  GstElement * pipeline_ = nullptr;
  GstElement * appsrc_ = nullptr;
  GstBus * bus_ = nullptr;
  GstClockTime frame_duration_ns_ = 0;
  uint64_t frame_idx_ = 0;

  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr sub_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<GstSenderNode>());
  rclcpp::shutdown();
  return 0;
}
