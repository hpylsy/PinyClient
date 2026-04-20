# PIONEER-client 总体说明

PIONEER-client 是 RoboMaster 自定义客户端实验项目，当前重点是打通协议解析、MQTT 状态接收、图传源切换与基础服务编排。

## 1. 核心逻辑

项目当前主链路分为三层。

1. 协议模型层：`models`

- 基于 protobuf 的消息模型定义。
- 统一序列化接口：protobuf / dict / json。
- 维护 topic 到消息类映射（`TOPIC2MSG`）。

2. 服务编排层：`service`

- MQTT 客户端收发与状态缓存（`RMMQTTClient` + `MQTTStateManager`）。
- 核心服务（`CoreService`）统一启动/停止。
- 根据 `DeployModeStatusSync.status` 动态切换图传源：
  - 普通模式：UDP 图传源。
  - 吊射模式：MQTT 图传源。

3. 工具层：`tools`

- 彩色日志与文件落盘（`RMColorLogger`）。

当前主运行入口是 `service/core_service.py`，它负责协议下行处理、状态机更新和图传模式切换。

## 2. 目录结构（当前）

- `config.py`：全局配置（MQTT 地址、端口、日志配置等）。
- `models/`：协议模型与常量。
- `service/`：核心服务、MQTT 客户端、图传接收器。
- `tools/`：日志工具。
- `app.py`、`web_server.py`：Web 侧实验入口（当前不作为主链路）。
- `templates/`、`static/`：Web 模板与静态资源。

## 3. 使用方式

## 3.1 环境准备

1. 安装 Python 3.10+（建议与当前项目环境保持一致）。
2. 安装依赖（按你本地环境实际安装）：

- `paho-mqtt`
- `protobuf`
- `opencv-python`
- `numpy`
- `flask`

## 3.2 启动udp测试图传流

在项目根目录进入 `service` 后启动：

```bash
python .\test_udp_sender.py
```

## 3.3 启动 Web 服务

```bash
python app.py
```

默认运行在 `127.0.0.1:5000`, 监听 `127.0.0.1:3334`，用于视频流实验页面验证。

## 4. 已实现功能

1. 协议模型统一管理

- `models/message.py` 已集中定义枚举、消息 dataclass 与 topic 映射。

2. 统一序列化能力

- 支持 protobuf / dict / json 互转，接收与发布链路已打通。

3. MQTT 客户端单线程模型

- 采用 `loop_start()` 网络循环，避免额外消息处理线程复杂度。

4. 线程安全状态管理

- `MQTTStateManager` 支持 topic 状态快照更新与读取。
- 支持空消息重置与默认值回填（用于 `status=0` 场景）。

5. 图传双源框架

- 已具备 UDP 图传接收重组。
- 已具备 MQTT 图传源接入骨架与模式切换逻辑。

6. 核心服务生命周期管理

- `CoreService` 提供 start/run/stop。
- 模式监控线程与停止流程已可控。

7. web端基础功能已经搭起

- 你可以使用 `python app.py`，并访问 `127.0.0.1:5000`，查看基础页面

## 5. 待实现功能

1. Web 端未完成

- 当前 Web 入口仍是实验性质，尚未形成完整前端交互面板。
- 页面状态展示、控制入口、错误态反馈、生产级路由结构仍需完善。

2. MQTT 图传接收逻辑未完成

- `MqttImgSource` 目前仅轮询 `CustomByteBlock` 更新，尚未完成分片重组、帧恢复与稳定输出。
- 与 UDP 图传接收相比，MQTT 图传链路还缺完整解包与帧管线。

3. 端到端联调完善

- 真实机器人/裁判系统环境下的稳定性、异常恢复与限流策略仍需加强。

4. 文档与测试补齐

- 需要补充更系统的集成测试与调试脚本说明。

## 6. 开发建议

1. 当前优先级建议

- 先完成 MQTT 图传接收链路（对齐 UDP 路径能力）。
- 再完善 Web 端展示与控制界面。

2. 调试建议

- 使用 `PIONEER_LOG_LEVEL=DEBUG` 提高日志粒度。
- 在交互模式下优先通过 `service.state_manager` 与 `service.stop()` 验证状态和生命周期。

## 7. 使用方法

1. 安装requirements.txt(不保证完全对，若有疏漏请反馈)(注意，不能用conda)
2. 安装gi(不能用conda的原因在这里)
   ```bash
   sudo apt update
   sudo apt install python3-gi
   ```
3. 启动(在根目录): `python app.py` 或 `python3 app.py`
4. 启动 `mock gateway`（注意，这里监听的MQTT 端口为3333）(cd service/sniper & source install/setup.zsh): `./install/doorlock_stream_e2e/bin/mock_gateway`
5. 启动 `gst_e2e_sender`: `./install/doorlock_stream_e2e/bin/gst_e2e_sender --mode file --file video.mp4 --host 127.0.0.1 --port 12345 --fps 30 --bitrate 300 --enable-display false`
6. 启动SharkDataServer（或其他MQTT Broker）
7. 启动 `test_udp_sender`: `cd service`, `python test_udp_sender.py`
