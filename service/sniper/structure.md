# Pacific Doorlock Sniper 源码结构与核心逻辑

## 1. 项目目标

该项目是一个基于 ROS 2 的低带宽图传链路，面向 RoboMaster 部署模式下的落点观测。

核心思路：
- 相机端拿到高分辨率图像。
- 编码端先做“对编码友好”的预处理，尽量保留运动目标、压缩静态背景信息。
- 用 H.264 做高压缩，再切成固定小包通过 ROS 2 话题发送。
- 解码端按流式方式重组并实时显示。

---

## 2. 运行入口与节点拓扑

主入口：`src/bringup/launch/sniper.launch.py`

默认启动三部分：
- `hik_camera::HikCameraNode`（可选，取决于本机是否有 Hik SDK 组件）
- `doorlock_sniper::VideoEncoderNode`（C++ 组件）
- `doorlock_decoder.video_decoder_node`（Python 节点）

数据流：

1. `hik_camera` 发布 `/image_raw` (`sensor_msgs/Image`)
2. `video_encoder` 订阅 `/image_raw`，输出 `/video_stream` (`doorlock_sniper/msg/VideoPacket`)
3. `video_decoder` 订阅 `/video_stream`，流式解码显示

其中编码容器采用 ComposableNodeContainer，将相机和编码器放在同进程并启用 intra-process 通信，降低拷贝开销。

---

## 3. 各包职责

### 3.1 bringup
- 作用：系统启动编排与参数集中配置
- 关键文件：`src/bringup/launch/sniper.launch.py`
- 特点：
	- 自动检测 `hik_camera` 组件是否可用。
	- 暴露编码参数（分辨率、码率、x264 preset、运动检测参数、调试 dump 参数等）。
	- 同时启动编码链路与解码显示链路。

### 3.2 hik_camera
- 作用：海康工业相机采集与 ROS 图像发布
- 关键文件：`src/hik_camera/src/hik_camera_node.cpp`
- 关键实现：
	- 调用海康 MVS SDK 枚举与拉流。
	- Bayer 原始图转 BGR（OpenCV `cvtColor`）。
	- 通过 `image_transport` 发布 `image_raw` 与 camera info。
	- 暴露曝光、增益等参数。

### 3.3 doorlock_sniper
- 作用：编码前图像预处理 + H.264 编码 + 固定包长分包发送
- 关键文件：
	- `src/doorlock_sniper/src/video_encoder_node.cpp`
	- `src/doorlock_sniper/msg/VideoPacket.msg`
- 核心输出消息：
	- `VideoPacket = sequence_id + timestamp_ns + uint8[150] data`

### 3.4 doorlock_decoder
- 作用：接收固定分片，流式解析 H.264，显示及调试输出
- 关键文件：`src/doorlock_decoder/doorlock_decoder/video_decoder_node.py`
- 关键实现：
	- 使用 PyAV (`av.CodecContext`) 进行 parse/decode。
	- 通过 `sequence_id` 做丢包检测，发现间断立即 reset 解码器。
	- 单独显示线程 + 队列，避免阻塞 ROS 回调。

---

## 4. 核心算法与工程策略（编码端）

核心在 `video_encoder_node.cpp`，可概括为“先降冗余，再压缩，再稳态传输”。

### 4.1 预处理链路

1. 中心裁剪 + 缩放
- 从原图中心裁出 `crop_size` 区域，缩放到 `output_size x output_size`。

2. 静态背景简化（可开关）
- 维护背景模型：`accumulateWeighted`。
- 计算当前帧与背景差分，阈值化获得运动掩码。
- 可配置腐蚀/膨胀以净化掩码。
- 对静态区域做模糊（以及低码率下灰度化背景），只保留运动区域细节。

3. 中心保护区
- 在中心区域强制保留细节（避免关键瞄准区域被静态简化吞掉）。

4. 运动拖影增强（可开关）
- 保存历史若干帧运动区，做时域 max 融合，增强高速目标可见性。
- 若全局运动比例过高，临时抑制拖影，防止画面污染。

### 4.2 编码策略（GStreamer + x264）

- 管线：`appsrc -> videoconvert -> x264enc -> h264parse -> appsink`
- 根据目标码率切换模式：
	- 低码率模式（<=80 kbps）：偏压缩效率（B 帧、lookahead、更高压缩参数）
	- 常规模式：偏低时延（zerolatency、少缓存）
- 输出 Annex-B byte-stream，并通过 parser 周期插入 SPS/PPS，利于流式重同步。

### 4.3 传输策略（固定 150B 分片）

1. 固定包长切片
- 从 H.264 字节流缓冲中，每 150B 构造一个 `VideoPacket`。
- 不足尾包在消息数组层面补零。

2. 滑动窗口限速
- 统计最近 `bandwidth_window_s` 时间窗内已发字节数。
- 超过 `bandwidth_limit_kbytes` 对应阈值则暂停继续发送，形成硬上限。

3. 最大排队时延保护
- 若发送背压导致缓冲过长，主动丢弃旧数据。
- 丢弃时尽量对齐 Annex-B 起始码，缩短解码异常持续时间。

该设计本质是在“画质-时延-稳态码率”之间做工程折中，优先保证可用性和实时性。

---

## 5. 解码端关键逻辑

`video_decoder_node.py` 的关键点：

- 输入单位是固定 150B 分片，不是完整帧。
- 通过 `codec.parse(chunk)` 先做码流解析，再 `decode(packet)` 出图像帧。
- 连续性依赖 `sequence_id`；一旦检测到 gap，立即重置解码器，等待新一组可解码关键数据。
- 显示层叠加瞄准辅助线与中心标记，并支持按帧间隔 dump 调试图。

---

## 6. 关键技术栈

语言与构建：
- C++17（编码器、相机驱动）
- Python 3（解码显示）
- CMake + ament_cmake（C++ 包）
- setuptools + ament_python（Python 包）

ROS 2 相关：
- `rclcpp` / `rclpy`
- `rclcpp_components`（Composable Node）
- `sensor_msgs/Image`
- 自定义消息：`doorlock_sniper/msg/VideoPacket`

多媒体与视觉：
- OpenCV（裁剪、缩放、差分、形态学、模糊、显示）
- GStreamer（`appsrc/appsink` + `x264enc` + `h264parse`）
- PyAV / FFmpeg（H.264 流式解析与解码）
- Hik MVS SDK（工业相机采集）

传输层策略：
- ROS 2 Reliable QoS + 深队列
- 应用层顺序号与丢包恢复
- 应用层滑动窗口限速与拥塞下缓冲裁剪

---

## 7. 代码阅读优先级（建议）

如果只看最核心文件，建议按下面顺序：

1. `src/bringup/launch/sniper.launch.py`
2. `src/doorlock_sniper/src/video_encoder_node.cpp`
3. `src/doorlock_sniper/msg/VideoPacket.msg`
4. `src/doorlock_decoder/doorlock_decoder/video_decoder_node.py`
5. `src/hik_camera/src/hik_camera_node.cpp`

这 5 个文件基本覆盖“采集-预处理-编码-分包-解码-显示”的完整主链路。
