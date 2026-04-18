# Pacific Doorlock Sniper

本仓库是一个面向 RoboMaster 场景的低带宽图传工程，核心由 3 个部件组成：

- E2E 图传处理链：图像预处理、编码、传输、解码
- ROS 2 桥接层：把图像流接到 ROS 生态
- Hik 相机驱动层：采集工业相机图像
  本文档重点说明这 3 个部件的逻辑和作用，并给出 Web 接入路径。

## 1. 架构总览

典型链路如下：

1. Hik 相机发布 ROS 话题图像
2. ROS 2 sender 或 E2E sender 将图像压缩编码并发送
3. 中间链路通过 UDP 或 MQTT 传输
4. 接收端解码后显示或再发布为 ROS 话题
5. Web 端从 ROS 话题或转码流获取画面

仓库中的主要目录：

- [src/doorlock_stream_e2e](src/doorlock_stream_e2e)
- [src/doorlock_stream_ros2](src/doorlock_stream_ros2)
- [src/hik_camera_ros2_driver](src/hik_camera_ros2_driver)
- [src/bringup/launch/sniper.launch.py](src/bringup/launch/sniper.launch.py)

## 2. 三个部件的作用

### 2.1 E2E 部件（doorlock_stream_e2e）

位置： [src/doorlock_stream_e2e](src/doorlock_stream_e2e)
作用：

- 发送端对图像做预处理（含动态 ROI、静态抑制、可选 NN 灯点引导）
- 使用 GStreamer + x264 做低带宽编码
- 支持 UDP 发送和 MQTT 解码接收链

关键可执行程序：

- gst_e2e_sender：发送端
- mqtt_test_receiver：MQTT 接收+解码端
- mock_gateway：UDP 到 MQTT 转发桥
  适用场景：
- 不依赖 ROS 2 话题时做独立图传
- 算法验证与带宽调优

### 2.2 ROS2 部件（doorlock_stream_ros2）

位置： [src/doorlock_stream_ros2](src/doorlock_stream_ros2)
作用：

- 把 ROS 图像话题发送到 UDP（gst_sender_node）
- 从 UDP 解码后发布回 ROS 话题（gst_receiver_node）
- 本地话题预览（topic_preview_node）

适用场景：

- 与导航、识别、控制等 ROS 模块打通
- 用标准 ROS 工具链做联调与录包

### 2.3 Hik 部件（hik_camera_ros2_driver）

位置： [src/hik_camera_ros2_driver](src/hik_camera_ros2_driver)

作用：

- 对接海康工业相机
- 发布图像和 camera_info 到 ROS 2 话题
- 支持曝光、增益、帧率、像素格式等参数配置
  适用场景：
- 真实设备采集入口
- 双相机/多相机场景下的基础图像源

## 3. 常用启动方式

### 3.1 一键 Bringup（推荐）

```bash
cd /home/hpy/pioneer/doorlock/Pacific_doorlock_sniper
colcon build --packages-select doorlock_stream_e2e doorlock_stream_ros2 hik_camera_ros2_driver bringup
source install/setup.zsh
ros2 launch bringup sniper.launch.py
```

说明：

- 启动参数在 [src/bringup/launch/sniper.launch.py](src/bringup/launch/sniper.launch.py)
- 可按需开启 ROS sender/receiver、话题预览、UDP 预览、SHM 预览

### 3.2 分开启动 E2E 三进程

1. 网关：

```bash
./install/doorlock_stream_e2e/bin/mock_gateway
```

2. 接收端：

```bash
./install/doorlock_stream_e2e/bin/mqtt_test_receiver --host 127.0.0.1 --port 1883 --enable-debug-ui true
```

3. 发送端：

```bash
./install/doorlock_stream_e2e/bin/gst_e2e_sender --mode file --file video.mp4 --host 127.0.0.1 --port 12345 --fps 30 --bitrate 300 --enable-display true
```

## 4. 如何接入 Web

建议分两种接法，根据你前端方案选择。

### 4.1 方案 A：基于 ROS 话题接 Web（推荐）

适合已有 ROS 系统和 Web 监控后台。
链路：

1. 相机或解码结果发布到 ROS 图像话题
2. 使用 rosbridge_suite 暴露 WebSocket
3. 前端通过 roslibjs 订阅图像（或配合压缩话题）

优点：

- 与 ROS 生态天然对接
- 数据语义完整（topic、frame_id、时间戳）

建议：

- 如果页面只看图像，建议同时发布 compressed 话题，降低带宽

### 4.2 方案 B：基于视频流协议接 Web

适合纯视频页面或低延迟直播。

做法：

1. 从接收端图像或 UDP 流拉取视频
2. 转为浏览器可消费协议（WebRTC/HLS/FLV）
3. 前端播放器直接拉流

优点：

- 前端实现简单
- 不依赖 ROS JS 生态

取舍：

- HLS 延迟高但兼容性好
- WebRTC 延迟低但部署复杂

## 5. 依赖要求

- Ubuntu Linux
- ROS 2
- OpenCV
- GStreamer 1.0
- Paho MQTT（用于 mqtt_test_receiver 与 mock_gateway）
- git branch -D Huangpy_clean2OpenVINO（仅 sender 侧 GuideLightDetector 依赖）

## 6. 维护建议

1. 核心库与业务插件解耦
2. 图像链路统一时间戳策略
3. Web 接入优先复用 ROS topic，不直接侵入核心编码流程
