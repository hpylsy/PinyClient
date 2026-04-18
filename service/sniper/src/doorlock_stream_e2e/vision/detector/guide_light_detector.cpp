#include "guide_light_detector.hpp"

#include <algorithm>
#include <cmath>

namespace rm_auto_aim
{
GuideLightDetector::GuideLightDetector(const LightParams & params) : l_(params) {}

void GuideLightDetector::setParameters(const LightParams & params) {
    if (
      l_.nn_model_path != params.nn_model_path || l_.nn_input_size != params.nn_input_size ||
      l_.use_nn != params.use_nn) {
        nn_initialized_ = false;
    }
    l_ = params;
}

std::vector<Light> GuideLightDetector::detect(const cv::Mat & input) {
    if (input.empty()) {
        lights_.clear();
        return lights_;
    }

    // Force NN-only path, then smooth with EMA.
    lights_ = smoothCandidates(findLightsByNN(input));
    return lights_;
}

std::vector<Light> GuideLightDetector::findLightsByNN(const cv::Mat & rgb_img) {
    std::vector<Light> candidates;
    if (!ensureNNReady()) {
        return candidates;
    }

    ResizeInfo res = resizeAndPad(rgb_img, cv::Size(l_.nn_input_size, l_.nn_input_size));
    if (res.resized_image.empty()) {
        return candidates;
    }

    ov::Tensor input_tensor(
      nn_model_.input().get_element_type(), nn_model_.input().get_shape(), res.resized_image.data);
    nn_infer_request_.set_input_tensor(input_tensor);
    nn_infer_request_.infer();

    const ov::Tensor & output_tensor = nn_infer_request_.get_output_tensor();
    float * detections = output_tensor.data<float>();
    ov::Shape output_shape = output_tensor.get_shape();
    if (output_shape.size() < 3) {
        return candidates;
    }

    std::vector<cv::Rect> boxes;
    std::vector<float> confidences;

    int rows = static_cast<int>(output_shape[1]);
    int cols = static_cast<int>(output_shape[2]);
    float scale_x = static_cast<float>(rgb_img.cols) /
      static_cast<float>(res.resized_image.cols - res.dw);
    float scale_y = static_cast<float>(rgb_img.rows) /
      static_cast<float>(res.resized_image.rows - res.dh);

    for (int i = 0; i < rows; ++i) {
        float * det = &detections[i * cols];
        float obj_conf = det[4];
        if (obj_conf < static_cast<float>(l_.nn_conf_thres)) {
            continue;
        }

        float * class_scores = &det[5];
        cv::Mat scores(1, cols - 5, CV_32FC1, class_scores);
        cv::Point class_id;
        double max_class_score;
        cv::minMaxLoc(scores, nullptr, &max_class_score, nullptr, &class_id);

        if (max_class_score < l_.nn_class_score_thres) {
            continue;
        }
        if (l_.nn_target_class_id >= 0 && class_id.x != l_.nn_target_class_id) {
            continue;
        }

        float x = det[0] * scale_x;
        float y = det[1] * scale_y;
        float w = det[2] * scale_x;
        float h = det[3] * scale_y;

        int left = std::max(0, static_cast<int>(x - w / 2.0f));
        int top = std::max(0, static_cast<int>(y - h / 2.0f));
        int width = std::min(static_cast<int>(w), rgb_img.cols - left);
        int height = std::min(static_cast<int>(h), rgb_img.rows - top);
        if (width <= 2 || height <= 2) {
            continue;
        }

        boxes.emplace_back(left, top, width, height);
        confidences.emplace_back(obj_conf * static_cast<float>(max_class_score));
    }

    std::vector<int> keep;
    cv::dnn::NMSBoxes(
      boxes, confidences, static_cast<float>(l_.nn_conf_thres),
      static_cast<float>(l_.nn_nms_thres), keep);

    candidates.reserve(keep.size());
    for (int idx : keep) {
        const cv::Rect & b = boxes[idx];
        cv::Point2f center(
          b.x + b.width / 2.0f,
          b.y + b.height / 2.0f);
        cv::RotatedRect rr(center, cv::Size2f(static_cast<float>(b.width), static_cast<float>(b.height)), 0.0f);
        candidates.emplace_back(Light(rr, std::vector<cv::Point>()));
    }

    return candidates;
}

std::vector<Light> GuideLightDetector::smoothCandidates(const std::vector<Light> & candidates) {
    std::vector<Light> lights;

    // 2. 时序滤波 (EMA Filter) 与抗闪烁逻辑
    if (!candidates.empty()) {
        // 在所有候选项中，优先选择面积最大的（最突出的主引导灯），天然过滤掉周围的噪点绿光
        auto best_it = std::max_element(candidates.begin(), candidates.end(),
            [](const Light& a, const Light& b) {
                return a.rect.size.area() < b.rect.size.area();
            });

        cv::Point2f current_center = best_it->center;
        float current_radius = best_it->rect.size.width / 2.0f;

        if (!has_prev_light_) {
            // 第一次检测到，初始化滤波器
            smoothed_center_ = current_center;
            smoothed_radius_ = current_radius;
            has_prev_light_ = true;
        } else {
            // 【核心 EMA 滤波算法】
            // alpha 值越小，抗抖动能力越强（越滞后）；alpha 值越大，跟随越紧密。
            const float alpha_pos = 0.1f;  // 位置平滑系数 (极其稳定)
            const float alpha_size = 0.02f; // 半径平滑系数更小，死死锁住圆的大小

            // 突变检测：如果云台大幅度甩动导致位置瞬间突变超过 100 像素，强制重置滤波器避免强拉扯
            if (cv::norm(current_center - smoothed_center_) > 100.0) {
                smoothed_center_ = current_center;
                smoothed_radius_ = current_radius;
            } else {
                // 平滑融合：新位置 = 当前测量值 * alpha + 历史记忆值 * (1 - alpha)
                smoothed_center_ = current_center * alpha_pos + smoothed_center_ * (1.0f - alpha_pos);
                smoothed_radius_ = current_radius * alpha_size + smoothed_radius_ * (1.0f - alpha_size);
            }
        }
        lost_light_frames_ = 0; // 重置丢帧计数器

        // 使用平滑后的数据构造最终的绿灯输出
        cv::RotatedRect smoothed_rect(smoothed_center_, cv::Size2f(smoothed_radius_ * 2.0f, smoothed_radius_ * 2.0f), 0.0f);
        lights.emplace_back(Light(smoothed_rect, std::vector<cv::Point>())); 

    } else {
        // 3. 护城河逻辑：如果当前帧没检测到绿灯（闪烁/被飞镖瞬间遮挡）
        lost_light_frames_++;
        
        if (lost_light_frames_ < 8 && has_prev_light_) {
            // 短暂丢帧（例如低于8帧），利用滤波器的记忆继续输出上一帧的绿灯！
            cv::RotatedRect smoothed_rect(smoothed_center_, cv::Size2f(smoothed_radius_ * 2.0f, smoothed_radius_ * 2.0f), 0.0f);
            lights.emplace_back(Light(smoothed_rect, std::vector<cv::Point>()));
        } else if (lost_light_frames_ >= 8) {
            // 彻底丢失超过8帧，清除历史记忆，等待下次重新捕捉
            has_prev_light_ = false;
        }
    }

    return lights;
}

GuideLightDetector::ResizeInfo GuideLightDetector::resizeAndPad(
        const cv::Mat & img, const cv::Size & new_shape) {
        ResizeInfo res;
        if (img.empty()) {
                return res;
        }

        float width = static_cast<float>(img.cols);
        float height = static_cast<float>(img.rows);
        float r = static_cast<float>(new_shape.width) / std::max(width, height);
        int new_unpad_w = static_cast<int>(std::round(width * r));
        int new_unpad_h = static_cast<int>(std::round(height * r));

        cv::resize(img, res.resized_image, cv::Size(new_unpad_w, new_unpad_h), 0, 0, cv::INTER_LINEAR);

        res.dw = new_shape.width - new_unpad_w;
        res.dh = new_shape.height - new_unpad_h;

        if (res.dh > 0 || res.dw > 0) {
                cv::copyMakeBorder(
                    res.resized_image, res.resized_image, 0, res.dh, 0, res.dw,
                    cv::BORDER_CONSTANT, cv::Scalar(114, 114, 114));
        }
        return res;
}

bool GuideLightDetector::ensureNNReady() {
        if (!l_.use_nn) {
                return false;
        }
        if (l_.nn_model_path.empty()) {
                return false;
        }

        if (nn_initialized_ && nn_loaded_model_path_ == l_.nn_model_path &&
            nn_loaded_input_size_ == l_.nn_input_size) {
                return true;
        }

        try {
                static ov::Core core;
                std::shared_ptr<ov::Model> model = core.read_model(l_.nn_model_path);

                ov::preprocess::PrePostProcessor ppp(model);
                ppp.input()
                    .tensor()
                    .set_element_type(ov::element::u8)
                    .set_layout("NHWC")
                    .set_color_format(ov::preprocess::ColorFormat::BGR);
                ppp.input()
                    .preprocess()
                    .convert_element_type(ov::element::f32)
                    .convert_color(ov::preprocess::ColorFormat::RGB)
                    .scale({255., 255., 255.});
                ppp.input().model().set_layout("NCHW");
                ppp.output().tensor().set_element_type(ov::element::f32);
                model = ppp.build();

                std::vector<std::string> devices = core.get_available_devices();
                bool has_gpu = std::find(devices.begin(), devices.end(), "GPU") != devices.end();

                if (has_gpu) {
                        ov::AnyMap gpu_config = {
                            {"PERFORMANCE_HINT", "LATENCY"},
                            {"MODEL_PRIORITY", "HIGH"},
                            {"GPU_ENABLE_LOOP_UNROLLING", "YES"}};
                        nn_model_ = core.compile_model(model, "GPU", gpu_config);
                } else {
                        ov::AnyMap cpu_config = {
                            {"PERFORMANCE_HINT", "THROUGHPUT"},
                            {"INFERENCE_PRECISION_HINT", "f16"}};
                        nn_model_ = core.compile_model(model, "CPU", cpu_config);
                }

                nn_infer_request_ = nn_model_.create_infer_request();
                nn_loaded_model_path_ = l_.nn_model_path;
                nn_loaded_input_size_ = l_.nn_input_size;
                nn_initialized_ = true;
                return true;
        } catch (...) {
                nn_initialized_ = false;
                return false;
        }
}

void GuideLightDetector::drawResults(cv::Mat & img) {
    for (const auto & light : lights_) {
        cv::ellipse(img, light.rect, cv::Scalar(0, 255, 0), 3); 
        cv::circle(img, light.center, 5, cv::Scalar(0, 0, 255), -1);
        // cv::putText(img, "Guide_Light", cv::Point(light.center.x + 10, light.center.y), 
        //             cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 0), 2);
    }
}

}  // namespace rm_auto_aim