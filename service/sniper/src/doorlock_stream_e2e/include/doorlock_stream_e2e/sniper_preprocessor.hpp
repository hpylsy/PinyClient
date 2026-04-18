#pragma once

#include <deque>
#include <optional>
#include <opencv2/opencv.hpp>

#include "config.hpp"

namespace doorlock_stream_e2e {

/**
 * Sniper 图像预处理器
 * 功能：中心裁剪、缩放、运动检测、背景简化
 */
class SniperPreprocessor {
public:
  explicit SniperPreprocessor(const SenderConfig& cfg) : cfg_(cfg) {}

  /**
   * 预处理一帧图像
   * @param input 输入原始图像 (BGR)
   * @param roi_downsample [输出] 降采样后的 ROI
   * @param static_removed [输出] 运动检测后的静止清理版本
   * @return 最终处理后的图像 (300×300)
   */
  cv::Mat preprocess(
    const cv::Mat& input,
    cv::Mat* roi_downsample = nullptr,
    cv::Mat* static_removed = nullptr,
    std::optional<cv::Point2f> track_point = std::nullopt);

private:
  SenderConfig cfg_;
  cv::Mat background_gray_f32_;
  cv::Mat motion_erode_kernel_;
  cv::Mat motion_dilate_kernel_;
  std::deque<cv::Mat> motion_mask_history_;
  std::deque<cv::Mat> trail_frame_history_;
};

}  // namespace doorlock_stream_e2e
