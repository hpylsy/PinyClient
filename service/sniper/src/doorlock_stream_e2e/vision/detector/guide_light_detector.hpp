#ifndef GUIDE_LIGHT_DETECTOR_HPP_
#define GUIDE_LIGHT_DETECTOR_HPP_

#include <openvino/openvino.hpp>
#include <opencv2/opencv.hpp>
#include <string>
#include <vector>

namespace rm_auto_aim
{
// 补全原版缺失的 Light 结构体
struct Light {
    cv::RotatedRect rect;
    cv::Point2f center;
    Light() = default;
    Light(cv::RotatedRect r, const std::vector<cv::Point>&) : rect(r), center(r.center) {}
};

class GuideLightDetector
{
public:
  struct LightParams
  {
    bool debug = false; // 【新增】绿灯独立调试开关

    bool use_nn = false;
    std::string nn_model_path = "";
    int nn_input_size = 320;
    double nn_conf_thres = 0.25;
    double nn_nms_thres = 0.45;
    double nn_class_score_thres = 0.7;
    int nn_target_class_id = -1;
  };

  explicit GuideLightDetector(const LightParams & params);
  void setParameters(const LightParams & params);

  std::vector<Light> detect(const cv::Mat & input);
  void drawResults(cv::Mat & img);

private:
  struct ResizeInfo
  {
    cv::Mat resized_image;
    int dw = 0;
    int dh = 0;
  };

  std::vector<Light> findLightsByNN(const cv::Mat & rgb_img);
  std::vector<Light> smoothCandidates(const std::vector<Light> & candidates);
  ResizeInfo resizeAndPad(const cv::Mat & img, const cv::Size & new_shape);
  bool ensureNNReady();

  LightParams l_;
  std::vector<Light> lights_;
  // 【新增】：滤波状态记忆变量
  cv::Point2f smoothed_center_{-1, -1};
  float smoothed_radius_{0.0f};
  bool has_prev_light_{false};
  int lost_light_frames_{0};

  bool nn_initialized_{false};
  std::string nn_loaded_model_path_;
  int nn_loaded_input_size_{0};
  ov::CompiledModel nn_model_;
  ov::InferRequest nn_infer_request_;
};

}  // namespace rm_auto_aim

#endif  // GUIDE_LIGHT_DETECTOR_HPP_