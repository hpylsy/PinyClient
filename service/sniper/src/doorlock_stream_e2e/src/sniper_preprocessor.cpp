#include "doorlock_stream_e2e/sniper_preprocessor.hpp"

#include <algorithm>

namespace doorlock_stream_e2e {

cv::Mat SniperPreprocessor::preprocess(
  const cv::Mat& input,
  cv::Mat* roi_downsample,
  cv::Mat* static_removed,
  std::optional<cv::Point2f> track_point) {
  int x = (input.cols - cfg_.crop_size) / 2;
  int y = (input.rows - cfg_.crop_size) / 2;
  if (track_point.has_value()) {
    x = static_cast<int>(std::round(track_point->x)) - cfg_.crop_size / 2;
    y = static_cast<int>(std::round(track_point->y)) - cfg_.crop_size / 2;
  }
  x = std::clamp(x, 0, std::max(0, input.cols - cfg_.crop_size));
  y = std::clamp(y, 0, std::max(0, input.rows - cfg_.crop_size));
  int w = std::min(cfg_.crop_size, input.cols - x);
  int h = std::min(cfg_.crop_size, input.rows - y);

  cv::Mat cropped = input(cv::Rect(x, y, w, h));
  cv::Mat resized;
  cv::resize(cropped, resized, cv::Size(cfg_.output_size, cfg_.output_size), 0, 0, cv::INTER_LINEAR);
  if (roi_downsample) {
    resized.copyTo(*roi_downsample);
  }

  cv::Mat working = resized;
  if (cfg_.force_monochrome) {
    cv::Mat gray_full;
    cv::cvtColor(working, gray_full, cv::COLOR_BGR2GRAY);
    cv::cvtColor(gray_full, working, cv::COLOR_GRAY2BGR);
  }

  if (!cfg_.static_simplify) {
    if (static_removed) {
      working.copyTo(*static_removed);
    }
    return working;
  }

  cv::Mat gray;
  cv::cvtColor(working, gray, cv::COLOR_BGR2GRAY);
  if (background_gray_f32_.empty()) {
    gray.convertTo(background_gray_f32_, CV_32F);
    if (static_removed) {
      working.copyTo(*static_removed);
    }
    return working;
  }

  cv::Mat bg_u8;
  cv::convertScaleAbs(background_gray_f32_, bg_u8);

  cv::Mat diff;
  cv::absdiff(gray, bg_u8, diff);

  cv::Mat motion_mask;
  cv::threshold(diff, motion_mask, cfg_.motion_threshold, 255, cv::THRESH_BINARY);

  if (cfg_.motion_erode_px > 0) {
    if (motion_erode_kernel_.empty()) {
      const int k = 2 * cfg_.motion_erode_px + 1;
      motion_erode_kernel_ = cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(k, k));
    }
    cv::erode(motion_mask, motion_mask, motion_erode_kernel_, cv::Point(-1, -1), 1);
  }

  if (cfg_.motion_dilate_px > 0) {
    if (motion_dilate_kernel_.empty()) {
      const int k = 2 * cfg_.motion_dilate_px + 1;
      motion_dilate_kernel_ = cv::getStructuringElement(cv::MORPH_ELLIPSE, cv::Size(k, k));
    }
    cv::dilate(motion_mask, motion_mask, motion_dilate_kernel_, cv::Point(-1, -1), 1);
  }

  const double motion_ratio = static_cast<double>(cv::countNonZero(motion_mask)) /
                              static_cast<double>(motion_mask.total());
  const bool suppress_trail = (motion_ratio >= cfg_.trail_disable_motion_ratio);

  if (cfg_.center_clear_size > 0) {
    const int clear_size = std::min({cfg_.center_clear_size, working.cols, working.rows});
    const int x0 = std::max(0, working.cols / 2 - clear_size / 2);
    const int y0 = std::max(0, working.rows / 2 - clear_size / 2);
    const int cw = std::min(clear_size, working.cols - x0);
    const int ch = std::min(clear_size, working.rows - y0);
    cv::rectangle(motion_mask, cv::Rect(x0, y0, cw, ch), cv::Scalar(255), cv::FILLED);
  }

  cv::Mat static_base = working.clone();
  cv::Mat blurred_static;
  cv::GaussianBlur(
    static_base,
    blurred_static,
    cv::Size(),
    std::max(0.0, cfg_.bg_blur_sigma),
    std::max(0.0, cfg_.bg_blur_sigma));

  cv::Mat focused = blurred_static.clone();
  working.copyTo(focused, motion_mask);
  if (static_removed) {
    focused.copyTo(*static_removed);
  }

  if (cfg_.motion_trail_frames > 0) {
    motion_mask_history_.push_back(motion_mask.clone());
    trail_frame_history_.push_back(working.clone());
    const size_t max_history = static_cast<size_t>(cfg_.motion_trail_frames + 1);
    while (motion_mask_history_.size() > max_history) {
      motion_mask_history_.pop_front();
    }
    while (trail_frame_history_.size() > max_history) {
      trail_frame_history_.pop_front();
    }

    const size_t history_size = motion_mask_history_.size();
    if (!suppress_trail && history_size > 1 && history_size == trail_frame_history_.size()) {
      cv::Mat trail_mask = motion_mask.clone();
      cv::Mat trail_img = working.clone();
      for (size_t i = 0; i < history_size - 1; ++i) {
        cv::bitwise_or(trail_mask, motion_mask_history_[i], trail_mask);
        cv::max(trail_img, trail_frame_history_[i], trail_img);
      }
      trail_img.copyTo(focused, trail_mask);
    }
  } else {
    motion_mask_history_.clear();
    trail_frame_history_.clear();
  }

  cv::accumulateWeighted(gray, background_gray_f32_, std::clamp(cfg_.bg_update_alpha, 0.001, 0.2));
  return focused;
}

}  // namespace doorlock_stream_e2e
