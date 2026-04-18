#if __has_include(<cv_bridge/cv_bridge.hpp>)
#include <cv_bridge/cv_bridge.hpp>
#else
#include <cv_bridge/cv_bridge.h>
#endif

#include <opencv2/opencv.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

#include <string>

class TopicPreviewNode : public rclcpp::Node
{
public:
  TopicPreviewNode()
  : Node("topic_preview_node")
  {
    input_topic_ = this->declare_parameter<std::string>("input_topic", "/image_raw");
    window_name_ = this->declare_parameter<std::string>("window_name", "ROS2 Topic Preview");
    display_scale_ = this->declare_parameter<int>("display_scale", 1);

    cv::namedWindow(window_name_, cv::WINDOW_NORMAL);

    sub_ = this->create_subscription<sensor_msgs::msg::Image>(
      input_topic_, rclcpp::SensorDataQoS(),
      std::bind(&TopicPreviewNode::on_image, this, std::placeholders::_1));

    RCLCPP_INFO(this->get_logger(), "topic_preview_node started. input=%s", input_topic_.c_str());
  }

  ~TopicPreviewNode() override
  {
    cv::destroyWindow(window_name_);
  }

private:
  void on_image(const sensor_msgs::msg::Image::SharedPtr msg)
  {
    cv_bridge::CvImageConstPtr cv_ptr;
    try {
      cv_ptr = cv_bridge::toCvShare(msg, "rgb8");
    } catch (const cv_bridge::Exception &) {
      try {
        cv_ptr = cv_bridge::toCvShare(msg, "bgr8");
      } catch (const cv_bridge::Exception & e) {
        RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 2000, "cv_bridge: %s", e.what());
        return;
      }
    }

    cv::Mat frame = cv_ptr->image;
    if (frame.empty()) {
      return;
    }

    cv::Mat show = frame;
    if (display_scale_ > 1) {
      cv::resize(frame, show, cv::Size(frame.cols * display_scale_, frame.rows * display_scale_), 0, 0, cv::INTER_NEAREST);
    }

    cv::imshow(window_name_, show);
    cv::waitKey(1);
  }

  std::string input_topic_;
  std::string window_name_;
  int display_scale_ = 1;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr sub_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<TopicPreviewNode>());
  rclcpp::shutdown();
  return 0;
}
