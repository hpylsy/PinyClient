#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <string>
#include <cstring>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "MvCameraControl.h"
#include "camera_info_manager/camera_info_manager.hpp"
#include "image_transport/image_transport.hpp"
#include "rclcpp/logging.hpp"
#include "rclcpp/utilities.hpp"

namespace hik_camera_ros2_driver
{
class HikCameraRos2DriverNode : public rclcpp::Node
{
public:
  explicit HikCameraRos2DriverNode(rclcpp::NodeOptions options)
  : Node("hik_camera_ros2_driver", options.use_intra_process_comms(true))
  {
    RCLCPP_INFO(this->get_logger(), "Starting HikCameraRos2DriverNode!");

    initializeCamera();
    declareParameters();
    startCamera();

    params_callback_handle_ = this->add_on_set_parameters_callback(
      std::bind(&HikCameraRos2DriverNode::dynamicParametersCallback, this, std::placeholders::_1));

    capture_thread_ = std::thread(&HikCameraRos2DriverNode::captureLoop, this);
  }

  ~HikCameraRos2DriverNode() override
  {
    if (capture_thread_.joinable()) {
      capture_thread_.join();
    }

    stopShmOutput();
    if (camera_handle_) {
      MV_CC_StopGrabbing(camera_handle_);
      MV_CC_CloseDevice(camera_handle_);
      MV_CC_DestroyHandle(&camera_handle_);
    }
    RCLCPP_INFO(this->get_logger(), "HikCameraRos2DriverNode destroyed!");
  }

private:
  struct ShmFrameHeader
  {
    uint32_t magic;
    uint32_t version;
    uint64_t sequence;
    uint64_t timestamp_ns;
    uint32_t width;
    uint32_t height;
    uint32_t step;
    uint32_t payload_size;
    uint32_t pixel_format;
    uint32_t reserved;
    char frame_id[64];
  };

  static constexpr uint32_t kShmMagic = 0x314D4853;  // "SHM1"
  static constexpr uint32_t kShmVersion = 1;
  static constexpr uint32_t kShmPixelFormatRgb8 = 1;

  bool initializeCamera()
  {
    MV_CC_DEVICE_INFO_LIST device_list;

    std::string required_serial = this->declare_parameter("camera_serial", "");
    int index = -1;

    // enum device
    while (rclcpp::ok()) {
      n_ret_ = MV_CC_EnumDevices(MV_USB_DEVICE, &device_list);
      if (n_ret_ != MV_OK) {
        RCLCPP_ERROR(this->get_logger(), "Failed to enumerate devices, retrying...");
        std::this_thread::sleep_for(std::chrono::seconds(1));
      } else if (device_list.nDeviceNum == 0) {
        RCLCPP_ERROR(this->get_logger(), "No camera found, retrying...");
        std::this_thread::sleep_for(std::chrono::seconds(1));
      } else {
        for (uint16_t i = 0; i < device_list.nDeviceNum; i++) {
          std::string serial_number(
            reinterpret_cast<const char *>(
              device_list.pDeviceInfo[i]->SpecialInfo.stUsb3VInfo.chSerialNumber));
          RCLCPP_INFO_THROTTLE(
            this->get_logger(), *this->get_clock(), 1000, "Found camera : %s",
            serial_number.c_str());
          if (serial_number == required_serial) {
            index = i;
            break;
          }
          RCLCPP_WARN_THROTTLE(
            this->get_logger(), *this->get_clock(), 1000, "Require camera: %s",
            required_serial.c_str());
        }
        if (index != -1) {
          break;
        }
      }
    }

    n_ret_ = MV_CC_CreateHandle(&camera_handle_, device_list.pDeviceInfo[index]);
    if (n_ret_ != MV_OK) {
      RCLCPP_ERROR(this->get_logger(), "Failed to create camera handle!");
      return false;
    }

    n_ret_ = MV_CC_OpenDevice(camera_handle_);
    if (n_ret_ != MV_OK) {
      RCLCPP_ERROR(this->get_logger(), "Failed to open camera device!");
      return false;
    }

    // Get camera information
    n_ret_ = MV_CC_GetImageInfo(camera_handle_, &img_info_);
    if (n_ret_ != MV_OK) {
      RCLCPP_ERROR(this->get_logger(), "Failed to get camera image info!");
      return false;
    }

    // Init convert param
    image_msg_.data.reserve(img_info_.nHeightMax * img_info_.nWidthMax * 3);
    convert_param_.nWidth = img_info_.nWidthValue;
    convert_param_.nHeight = img_info_.nHeightValue;
    convert_param_.enDstPixelType = PixelType_Gvsp_RGB8_Packed;

    return true;
  }

  void declareParameters()
  {
    rcl_interfaces::msg::ParameterDescriptor param_desc;
    MVCC_FLOATVALUE f_value;
    param_desc.integer_range.resize(1);
    param_desc.integer_range[0].step = 1;

    // Acquisition frame rate
    param_desc.description = "Acquisition frame rate in Hz";
    MV_CC_GetFloatValue(camera_handle_, "AcquisitionFrameRate", &f_value);
    param_desc.integer_range[0].from_value = f_value.fMin;
    param_desc.integer_range[0].to_value = f_value.fMax;
    double acquisition_frame_rate =
      this->declare_parameter("acquisition_frame_rate", 165.0, param_desc);
    MV_CC_SetBoolValue(camera_handle_, "AcquisitionFrameRateEnable", true);
    MV_CC_SetFloatValue(camera_handle_, "AcquisitionFrameRate", acquisition_frame_rate);
    RCLCPP_INFO(this->get_logger(), "Acquisition frame rate: %f", acquisition_frame_rate);

    // Exposure time
    param_desc.description = "Exposure time in microseconds";
    MV_CC_GetFloatValue(camera_handle_, "ExposureTime", &f_value);
    param_desc.integer_range[0].from_value = f_value.fMin;
    param_desc.integer_range[0].to_value = f_value.fMax;
    double exposure_time = this->declare_parameter("exposure_time", 5000, param_desc);
    MV_CC_SetFloatValue(camera_handle_, "ExposureTime", exposure_time);
    RCLCPP_INFO(this->get_logger(), "Exposure time: %f", exposure_time);

    // Gain
    param_desc.description = "Gain";
    MV_CC_GetFloatValue(camera_handle_, "Gain", &f_value);
    param_desc.integer_range[0].from_value = f_value.fMin;
    param_desc.integer_range[0].to_value = f_value.fMax;
    double gain = this->declare_parameter("gain", f_value.fCurValue, param_desc);
    MV_CC_SetFloatValue(camera_handle_, "Gain", gain);
    RCLCPP_INFO(this->get_logger(), "Gain: %f", gain);

    int status;

    // Pixel format
    param_desc.description = "Pixel Format";
    std::string pixel_format = this->declare_parameter("pixel_format", "RGB8Packed", param_desc);
    status = MV_CC_SetEnumValueByString(camera_handle_, "PixelFormat", pixel_format.c_str());
    if (status == MV_OK) {
      RCLCPP_INFO(this->get_logger(), "Pixel Format set to %s", pixel_format.c_str());
    } else {
      RCLCPP_ERROR(this->get_logger(), "Failed to set Pixel Format, status = %d", status);
    }

    // Optional shared-memory output for non-ROS local consumers.
    enable_shm_output_ = this->declare_parameter("enable_shm_output", false);
    shm_name_ = this->declare_parameter("shm_name", std::string("/hik_camera_rgb"));
    shm_max_bytes_ = this->declare_parameter("shm_max_bytes", 0);
  }

  bool startShmOutput()
  {
    if (!enable_shm_output_) {
      return true;
    }

    if (shm_name_.empty() || shm_name_[0] != '/') {
      RCLCPP_ERROR(this->get_logger(), "Invalid shm_name '%s', it must start with '/'", shm_name_.c_str());
      return false;
    }

    const size_t min_payload_capacity =
      static_cast<size_t>(img_info_.nWidthMax) * static_cast<size_t>(img_info_.nHeightMax) * 3;
    const size_t requested_payload_capacity =
      (shm_max_bytes_ > 0) ? static_cast<size_t>(shm_max_bytes_) : static_cast<size_t>(0);

    shm_payload_capacity_ = std::max(min_payload_capacity, requested_payload_capacity);
    shm_total_bytes_ = sizeof(ShmFrameHeader) + shm_payload_capacity_;

    shm_fd_ = shm_open(shm_name_.c_str(), O_CREAT | O_RDWR, 0666);
    if (shm_fd_ < 0) {
      RCLCPP_ERROR(this->get_logger(), "Failed to shm_open(%s): %s", shm_name_.c_str(), std::strerror(errno));
      return false;
    }

    if (ftruncate(shm_fd_, static_cast<off_t>(shm_total_bytes_)) != 0) {
      RCLCPP_ERROR(this->get_logger(), "Failed to ftruncate shared memory: %s", std::strerror(errno));
      close(shm_fd_);
      shm_fd_ = -1;
      return false;
    }

    shm_addr_ = mmap(nullptr, shm_total_bytes_, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd_, 0);
    if (shm_addr_ == MAP_FAILED) {
      RCLCPP_ERROR(this->get_logger(), "Failed to mmap shared memory: %s", std::strerror(errno));
      shm_addr_ = nullptr;
      close(shm_fd_);
      shm_fd_ = -1;
      return false;
    }

    std::memset(shm_addr_, 0, shm_total_bytes_);
    auto * header = reinterpret_cast<ShmFrameHeader *>(shm_addr_);
    header->magic = kShmMagic;
    header->version = kShmVersion;
    header->pixel_format = kShmPixelFormatRgb8;

    shm_frame_idx_ = 0;
    RCLCPP_INFO(
      this->get_logger(), "Shared memory output enabled: name=%s bytes=%zu payload=%zu",
      shm_name_.c_str(), shm_total_bytes_, shm_payload_capacity_);
    return true;
  }

  void stopShmOutput()
  {
    if (shm_addr_ != nullptr) {
      munmap(shm_addr_, shm_total_bytes_);
      shm_addr_ = nullptr;
    }
    shm_total_bytes_ = 0;
    shm_payload_capacity_ = 0;
    if (shm_fd_ >= 0) {
      close(shm_fd_);
      shm_fd_ = -1;
    }
  }

  bool pushFrameToShm(const sensor_msgs::msg::Image & image_msg)
  {
    if (!enable_shm_output_ || shm_addr_ == nullptr) {
      return true;
    }

    const size_t payload_bytes = image_msg.data.size();
    if (payload_bytes > shm_payload_capacity_) {
      RCLCPP_ERROR(
        this->get_logger(),
        "Frame size (%zu) exceeds shared memory payload capacity (%zu)",
        payload_bytes, shm_payload_capacity_);
      return false;
    }

    auto * header = reinterpret_cast<ShmFrameHeader *>(shm_addr_);
    auto * payload = reinterpret_cast<uint8_t *>(shm_addr_) + sizeof(ShmFrameHeader);

    const uint64_t seq_begin = (shm_frame_idx_ << 1) + 1;
    header->sequence = seq_begin;
    std::atomic_thread_fence(std::memory_order_release);

    std::memcpy(payload, image_msg.data.data(), payload_bytes);

    header->timestamp_ns =
      static_cast<uint64_t>(image_msg.header.stamp.sec) * 1000000000ULL +
      static_cast<uint64_t>(image_msg.header.stamp.nanosec);
    header->width = image_msg.width;
    header->height = image_msg.height;
    header->step = image_msg.step;
    header->payload_size = static_cast<uint32_t>(payload_bytes);
    header->pixel_format = kShmPixelFormatRgb8;
    std::strncpy(header->frame_id, image_msg.header.frame_id.c_str(), sizeof(header->frame_id) - 1);
    header->frame_id[sizeof(header->frame_id) - 1] = '\0';

    std::atomic_thread_fence(std::memory_order_release);
    header->sequence = seq_begin + 1;
    ++shm_frame_idx_;
    return true;
  }

  void startCamera()
  {
    enable_ros_publish_ = this->declare_parameter("enable_ros_publish", true);
    bool use_sensor_data_qos = this->declare_parameter("use_sensor_data_qos", true);
    camera_name_ = this->declare_parameter("camera_name", "");
    frame_id_ = this->declare_parameter("frame_id", camera_name_ + "_optical_frame");
    camera_topic_ = this->declare_parameter("camera_topic", camera_name_ + "image_raw");

    if (enable_ros_publish_) {
      auto qos = use_sensor_data_qos ? rmw_qos_profile_sensor_data : rmw_qos_profile_default;
      camera_pub_ = image_transport::create_camera_publisher(this, camera_topic_, qos);
    } else {
      RCLCPP_WARN(this->get_logger(), "ROS topic publish disabled by parameter enable_ros_publish=false");
    }

    MV_CC_StartGrabbing(camera_handle_);

    // Load camera info
    if (enable_ros_publish_) {
      camera_info_manager_ =
        std::make_unique<camera_info_manager::CameraInfoManager>(this, camera_name_);
      auto camera_info_url = this->declare_parameter(
        "camera_info_url", "package://hik_camera_ros2_driver/config/camera_info.yaml");
      if (camera_info_manager_->validateURL(camera_info_url)) {
        camera_info_manager_->loadCameraInfo(camera_info_url);
        camera_info_msg_ = camera_info_manager_->getCameraInfo();
      } else {
        RCLCPP_WARN(this->get_logger(), "Invalid camera info URL: %s", camera_info_url.c_str());
      }
    }

    if (!startShmOutput()) {
      RCLCPP_FATAL(this->get_logger(), "Failed to start optional shared-memory output");
      rclcpp::shutdown();
    }
  }

  void captureLoop()
  {
    MV_FRAME_OUT out_frame;
    RCLCPP_INFO(this->get_logger(), "Publishing image!");

    image_msg_.header.frame_id = frame_id_;
    image_msg_.encoding = "rgb8";

    while (rclcpp::ok()) {
      n_ret_ = MV_CC_GetImageBuffer(camera_handle_, &out_frame, 1000);
      if (MV_OK == n_ret_) {
        image_msg_.height = out_frame.stFrameInfo.nHeight;
        image_msg_.width = out_frame.stFrameInfo.nWidth;
        image_msg_.step = out_frame.stFrameInfo.nWidth * 3;
        image_msg_.data.resize(static_cast<size_t>(image_msg_.width) * image_msg_.height * 3);

        convert_param_.pDstBuffer = image_msg_.data.data();
        convert_param_.nDstBufferSize = image_msg_.data.size();
        convert_param_.pSrcData = out_frame.pBufAddr;
        convert_param_.nSrcDataLen = out_frame.stFrameInfo.nFrameLen;
        convert_param_.enSrcPixelType = out_frame.stFrameInfo.enPixelType;

        const int convert_status = MV_CC_ConvertPixelType(camera_handle_, &convert_param_);
        if (convert_status != MV_OK) {
          RCLCPP_WARN(this->get_logger(), "Convert pixel type failed! status=[%x]", convert_status);
          MV_CC_FreeImageBuffer(camera_handle_, &out_frame);
          continue;
        }

        image_msg_.header.stamp = this->now();

        if (enable_ros_publish_) {
          camera_info_msg_.header = image_msg_.header;
          camera_pub_.publish(image_msg_, camera_info_msg_);
        }

        if (!pushFrameToShm(image_msg_)) {
          RCLCPP_ERROR(this->get_logger(), "SHM push failed, disable shared-memory output");
          enable_shm_output_ = false;
          stopShmOutput();
        }

        MV_CC_FreeImageBuffer(camera_handle_, &out_frame);

        static auto last_log_time = std::chrono::steady_clock::now();
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - last_log_time).count() >= 3) {
          MVCC_FLOATVALUE f_value;
          MV_CC_GetFloatValue(camera_handle_, "ResultingFrameRate", &f_value);
          RCLCPP_DEBUG(this->get_logger(), "ResultingFrameRate: %f Hz", f_value.fCurValue);
          last_log_time = now;
        }

      } else {
        RCLCPP_WARN(this->get_logger(), "Get buffer failed! nRet: [%x]", n_ret_);
        MV_CC_StopGrabbing(camera_handle_);
        MV_CC_StartGrabbing(camera_handle_);
        fail_count_++;
      }

      if (fail_count_ > 5) {
        RCLCPP_FATAL(this->get_logger(), "Camera failed!");
        rclcpp::shutdown();
      }
    }
  }

  rcl_interfaces::msg::SetParametersResult dynamicParametersCallback(
    const std::vector<rclcpp::Parameter> & parameters)
  {
    rcl_interfaces::msg::SetParametersResult result;
    result.successful = true;

    for (const auto & param : parameters) {
      const auto & type = param.get_type();
      const auto & name = param.get_name();
      int status = MV_OK;

      if (type == rclcpp::ParameterType::PARAMETER_DOUBLE) {
        if (name == "gain") {
          status = MV_CC_SetFloatValue(camera_handle_, "Gain", param.as_double());
        } else {
          result.successful = false;
          result.reason = "Unknown parameter: " + name;
          continue;
        }
      } else if (type == rclcpp::ParameterType::PARAMETER_INTEGER) {
        if (name == "exposure_time") {
          status = MV_CC_SetFloatValue(camera_handle_, "ExposureTime", param.as_int());
        } else {
          result.successful = false;
          result.reason = "Unknown parameter: " + name;
          continue;
        }
      } else {
        result.successful = false;
        result.reason = "Unsupported parameter type for: " + name;
        continue;
      }

      if (status != MV_OK) {
        result.successful = false;
        result.reason = "Failed to set " + name + ", status = " + std::to_string(status);
      }
    }

    return result;
  }

  void * camera_handle_ = nullptr;
  int n_ret_ = MV_OK;
  MV_IMAGE_BASIC_INFO img_info_;
  MV_CC_PIXEL_CONVERT_PARAM convert_param_;

  sensor_msgs::msg::Image image_msg_;
  sensor_msgs::msg::CameraInfo camera_info_msg_;
  image_transport::CameraPublisher camera_pub_;
  std::unique_ptr<camera_info_manager::CameraInfoManager> camera_info_manager_;
  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr params_callback_handle_;

  std::string camera_name_;
  std::string frame_id_;
  std::string camera_topic_;

  std::thread capture_thread_;
  int fail_count_ = 0;

  bool enable_ros_publish_ = true;

  bool enable_shm_output_ = false;
  std::string shm_name_ = "/hik_camera_rgb";
  int shm_max_bytes_ = 0;
  int shm_fd_ = -1;
  void * shm_addr_ = nullptr;
  size_t shm_total_bytes_ = 0;
  size_t shm_payload_capacity_ = 0;
  uint64_t shm_frame_idx_ = 0;

};
}  // namespace hik_camera_ros2_driver

#include "rclcpp_components/register_node_macro.hpp"
RCLCPP_COMPONENTS_REGISTER_NODE(hik_camera_ros2_driver::HikCameraRos2DriverNode)
