# tools 目录说明

本目录存放通用工具模块，当前核心工具包括：

- `rm_logger.py`: 统一彩色日志输出与可选文件落盘。
- `local_mqtt_video_sim.py`: 本机端到端图传模拟工具，必须手动运行，不会被正常 `app.py` 启动。

## local_mqtt_video_sim.py 图传工具

用途：在不接真实下位机/选手端图传链路的情况下，模拟完整低带宽图传路径：

```text
视频文件或 Hik 相机共享内存
  -> doorlock_stream_e2e/gst_e2e_sender
  -> rm_serial_driver 5 个 63B 子包
  -> 工具内虚拟下位机合包
  -> MQTT CustomByteBlock
  -> PinyClient Web 解码播放
```

该工具用于回归测试分包、合包、MQTT 发布、H264 RTP 解码和 Web 播放。正常上下位机连接时不要运行它。

常用命令：

```bash
# 只检查 300B -> 5x63B -> 300B -> CustomByteBlock 协议链路
python3 tools/local_mqtt_video_sim.py --dry-run

# 用视频文件跑完整链路，同时启动 PinyClient Web
python3 tools/local_mqtt_video_sim.py \
  --source-mode file \
  --video /home/hpy/pioneer/hero/source/8.mp4 \
  --quiet-sender \
  --quiet-ros \
  --web-port 5053

# 逐个播放目录内视频，适合检查 ROI、绿灯、发送前画面和接收画面
python3 tools/local_mqtt_video_sim.py \
  --source-mode file \
  --video-dir /home/hpy/pioneer/hero/source \
  --video-pattern '*.mp4' \
  --sender-display \
  --quiet-ros

# 用真实 Hik 相机共享内存作为输入
python3 tools/local_mqtt_video_sim.py \
  --source-mode shm \
  --quiet-sender \
  --quiet-ros
```

关键开关：

- `--dry-run`: 只跑协议自检，不启动 ROS、MQTT Web 或相机。
- `--source-mode file|shm`: 选择视频文件或相机共享内存输入。
- `--no-web`: 不启动 PinyClient Web，只看链路统计。
- `--sender-display`: 打开发送端调试窗口。
- `--run-seconds N`: 自动运行 N 秒后退出。
- `--stats-interval N`: 控制统计日志输出间隔。

该工具会在运行时创建虚拟串口和临时 ROS 参数文件，退出时清理。若进程被强杀，优先检查是否残留 ROS 节点或占用端口。

## rm_logger.py 核心逻辑

`RMColorLogger` 封装了 Python `logging`，提供以下能力：

1. 统一日志格式：
   - 时间
   - 级别
   - logger 名称
   - 文件名:行号
   - 消息

2. 分级配色主题：
   - `DEBUG / INFO / WARNING / ERROR / CRITICAL`
   - 不同级别使用不同前景/背景色和样式。

3. 运行时可配置日志级别：
   - 优先读取环境变量 `PIONEER_LOG_LEVEL`
   - 默认读取 `config.py` 中的 `Config.LEVEL`

4. 可选文件日志：
   - 当 `Config.RECORD_LOG=True` 时，按天写入 `Config.LOG_DIR`。
   - 文件名格式：`{logger_name}_YYYY_MM_DD.log`。

5. 调用方位置信息准确：
   - `debug/info/warning/error/critical` 统一设置 `stacklevel=2`，
     让日志中的文件与行号指向业务调用处，而不是 logger 封装内部。

## 使用方式

```python
from tools.rm_logger import RMColorLogger

logger = RMColorLogger("CoreService")
logger.info("服务启动")
logger.error("发生异常")
```

临时调高日志级别（PowerShell）：

```powershell
$env:PIONEER_LOG_LEVEL = "DEBUG"
```

## 维护建议

1. 新增工具模块后，保持“单工具单职责”。
2. 若工具被多模块复用，优先放在 `tools`，避免在 `service`/`models` 重复实现。
3. 日志工具变更后，优先验证：
   - 颜色输出是否正常。
   - 文件落盘路径是否可写。
   - stacklevel 行号是否定位到调用方。
