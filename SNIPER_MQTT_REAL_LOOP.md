# Sniper MQTT Real Loop Handoff

本文记录英雄低带宽图传当前版本和真实环路排查方法。这里的真实环路指：

```text
sniper_camera
-> /hik_camera_rgb shared memory
-> doorlock_stream_e2e/gst_e2e_sender
-> ROS2 /sniper_packets
-> rm_serial_driver
-> lower computer / referee system / player client
-> MQTT 192.168.12.1:3333 topic CustomByteBlock
-> PinyClient
-> /video_feed
-> Web
```

本地 mock、虚拟串口、本机 MQTT 只能用于回归和定位，最终有效性以真实环路为准。

## Run

先启动机器人侧 bringup：

```bash
cd /home/hpy/pioneer/hero
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rm_vision_bringup vision_bringup.launch.py
```

再启动 PinyClient，并显式指定 MQTT 图传源：

```bash
cd /home/hpy/pioneer/doorlock/PinyClient
python3 app.py \
  --video-source mqtt \
  --mqtt-host 192.168.12.1 \
  --mqtt-port 3333
```

打开：

```text
http://127.0.0.1:5000/
```

注意：不要为了联调去改 `app.py` 默认值。`python3 app.py` 默认仍是 `--video-source auto`，英雄会按 `DeployModeStatusSync.status` 自动切换 UDP/MQTT。真实图传调试时用上面的显式参数。

## Diff From Fork

当前本地代码相对 `origin/main` 的主要差异如下。

PinyClient:

- `service/img_receiver.py`
  - `CustomByteBlock` 接收端支持官方 protobuf 外层，也兼容裸 300B 固定包。
  - 固定包仍是 300B，但跳过污染区 `data[33:54)`，有效 RTP payload 上限从 298B 变为 277B。
  - 增加 MQTT/RTP/decoded frame 统计，包括 `latest_frame` 更新时间、队列长度、不同 payload 包装来源计数。
  - MQTT H264 解码链路使用 GStreamer `appsrc -> rtpjitterbuffer -> rtph264depay -> h264parse -> avdec_h264 -> appsink`。
  - 解码出的帧会叠加接收端时间戳和 decoded frame counter，方便肉眼判断 Web 是否在更新。
  - 提供 `reset_decoder()`，用于本机模拟或跨视频测试时清理 H264 旧参考帧。

- `tools/local_mqtt_video_sim.py`
  - 本机端到端模拟工具增强，能跑视频/相机源、虚拟串口、MQTT bridge、PinyClient Web。
  - 增加 5x63B 子包重组、CRC、自定义 300B payload、可选预序列化 `CustomByteBlock` 的 dry-run 检查。
  - 这个工具只用于本地验证，不代表真实裁判链路一定可用。

rm_vision_hero:

- `doorlock_stream_e2e/include/doorlock_stream_e2e/packet_protocol.hpp`
  - 固定包协议保持外层 300B。
  - `data[33:54)` 作为保留区，发送端填 0，接收端跳过。
  - 当前有效 RTP payload 上限为 277B。
  - 另有实验性的 `SerializedCustomBlockProtocol`，用于测试预序列化内层 `CustomByteBlock`，默认关闭。

- `doorlock_stream_e2e/include/doorlock_stream_e2e/gst_encoder.hpp`
  - x264 关键帧间隔改为 `fps`，即约每秒一个 IDR。
  - 保留 `repeat-headers=1` 和 `config-interval=-1`，让 SPS/PPS 更容易随关键帧恢复解码。

- `doorlock_stream_e2e/include/doorlock_stream_e2e/config.hpp`
  - 默认 `motion_trail_frames` 调整为 10。
  - 增加 `enable_custom_block_serialization` 开关，默认 false。

- `doorlock_stream_e2e/src/sniper_preprocessor.cpp`
  - 中心 `150x150` 区域保留彩色和细节。
  - 中心外区域灰度化，以降低 H264 编码压力。
  - 检测到的运动弹丸和残影区域保留颜色。
  - 增加 `updateTrailOnly()`，SHM 相机模式下可用相机 30fps 持续更新拖影历史，同时 sender 仍按低 fps 编码发送。

- `doorlock_stream_e2e/src/gst_e2e_sender.cpp`
  - SHM 模式启用 lightweight trail-only updater。
  - 发送端默认按 30Hz 控制 RTP packet 输出，不是视频帧率。
  - 目前配置建议是 `fps=10`、`bitrate=40`、`output_size=300`。
  - 输出帧叠加发送端时间戳和 frame counter，便于和接收端 overlay 对比延迟。
  - 支持从 launch/config 传入 `--enable-custom-block-serialization`，默认 false。

- `rm_vision/rm_vision_bringup/config/node_params.yaml`
  - 拆成 `/armor_camera` 和 `/sniper_camera` 两个 Hik 相机节点参数。
  - `/gst_e2e_sender` 增加 sender 图传参数。

- `rm_vision/rm_vision_bringup/launch/vision_bringup.launch.py`
  - `vision_bringup` 会按 `launch_params.yaml` 启动双相机。
  - 如果 `enable_sniper_sender: true`，会自动启动 `gst_e2e_sender --mode shm`。
  - sender 的 fps、bitrate、output_size、display、custom serialization 都从 `node_params.yaml` 读取。

- `doorlock_stream_e2e/CMakeLists.txt` 和测试文件
  - 增加 `test_packet_protocol`。
  - `rm_serial_driver/test/test_sniper_packet_contract.cpp` 强化 300B -> 5 个 63B 子包合同检查。

## Dual Camera YAMLs

双相机相关主要看两个 YAML 文件，不要只按旧单相机习惯改 `/camera_node`。

### `launch_params.yaml`

路径：

```text
/home/hpy/pioneer/hero/src/rm_vision_hero/rm_vision/rm_vision_bringup/config/launch_params.yaml
```

作用：决定 bringup 启动哪些节点。

当前关键配置：

```yaml
camera: hik

enable_armor_camera: true
enable_sniper_camera: true
enable_sniper_sender: true
enable_lob_vision: false

virtual_serial: false
```

含义：

- `enable_armor_camera: true`
  - 启动自瞄相机节点 `/armor_camera`。
  - 输出正常自瞄 ROS topic `/image_raw`。

- `enable_sniper_camera: true`
  - 启动图传相机节点 `/sniper_camera`。
  - 默认不发布 ROS 图像 topic，只写共享内存 `/hik_camera_rgb`。

- `enable_sniper_sender: true`
  - 启动 `doorlock_stream_e2e/gst_e2e_sender`。
  - sender 从 `/hik_camera_rgb` 读图，发到 `/sniper_packets`。

- `virtual_serial: false`
  - 使用真实串口 `rm_serial_driver_node`。
  - 真实环路调试必须保持 false。

### `node_params.yaml`

路径：

```text
/home/hpy/pioneer/hero/src/rm_vision_hero/rm_vision/rm_vision_bringup/config/node_params.yaml
```

作用：给各 ROS 节点提供参数。双相机时重点是节点名对应参数块。

#### `/armor_camera`

当前用途：自瞄相机。

当前关键参数：

```yaml
/armor_camera:
  ros__parameters:
    camera_serial: "DA8657813"
    camera_name: "armor_camera"
    frame_id: "armor_camera_optical_frame"
    camera_topic: "/image_raw"
    enable_ros_publish: true
    acquisition_frame_rate: 250.0
    enable_shm_output: false
```

注意：

- `vision_bringup.launch.py` 里 Hik 自瞄节点名字是 `armor_camera`，所以这里必须改 `/armor_camera`，不是 `/camera_node`。
- 自瞄相机发布 `/image_raw`，供 armor detector 使用。
- 自瞄相机默认不写共享内存。

#### `/sniper_camera`

当前用途：低带宽图传相机。

当前关键参数：

```yaml
/sniper_camera:
  ros__parameters:
    camera_serial: "DA2583832"
    camera_name: "sniper_camera"
    frame_id: "sniper_camera_optical_frame"
    camera_topic: "/sniper/image_raw"
    enable_ros_publish: false
    acquisition_frame_rate: 30.0
    exposure_time: 16000
    gain: 16.0
    enable_shm_output: true
    shm_name: "/hik_camera_rgb"
```

注意：

- `vision_bringup.launch.py` 里图传相机节点名字是 `sniper_camera`，所以这里必须改 `/sniper_camera`。
- 图传相机默认不发布 ROS 图像 topic，避免额外负载。
- 图传相机写共享内存 `/hik_camera_rgb`，sender 从这里读图。
- 相机采集是 30fps，sender 编码发送不等于 30fps。

#### `/gst_e2e_sender`

当前用途：低带宽 H264/RTP/CustomByteBlock sender 参数。

当前关键参数：

```yaml
/gst_e2e_sender:
  ros__parameters:
    fps: 10
    bitrate: 40
    output_size: 300
    enable_display: false
    enable_custom_block_serialization: false
```

注意：

- `fps: 10` 是 sender 输入编码帧率目标。
- `bitrate: 40` 是 x264 kbps 目标，当前真实环路下比较均衡。
- `/sniper_packets` 看到约 25-30Hz 是 RTP packet 频率，不是 Web 视频真实变化帧率。
- `enable_custom_block_serialization` 默认 false，不要随便打开。真实可用版本使用外层 300B 固定包，由裁判/选手端转成 MQTT `CustomByteBlock`。

#### `/camera_node`

当前用途：兼容旧单相机 launch 和 calibrate 流程。

```yaml
/camera_node:
  ros__parameters:
    camera_serial: "DA8657838"
    camera_name: "armor_camera"
    camera_topic: "/image_raw"
```

注意：

- `vision_bringup.launch.py` 的 Hik 双相机路径不使用 `/camera_node`。
- 旧单相机用户容易只改 `/camera_node`，这对当前双相机 bringup 不生效。
- 要改当前比赛 bringup 的设备号，请改 `/armor_camera` 和 `/sniper_camera`。
- 如果跑 `calibrate.py` 或旧单相机 launch，再检查 `/camera_node`。

## Current Expected Runtime

当前真实环路比较稳定的一组参数：

```text
sniper_camera acquisition_frame_rate = 30.0
gst_e2e_sender fps = 10
gst_e2e_sender bitrate = 40
gst_e2e_sender output_size = 300
CustomByteBlock packet = 300B
reserved dirty block = data[33:54)
effective RTP payload max = 277B
serial split = 5 x 63B
```

最近相机真实环路实测大致表现：

```text
/video_feed HTTP fps: about 29 fps
JPEG hash change rate: about 7-9 Hz
/sniper_packets: about 25-30 Hz
tcpdump CustomByteBlock: about 250-270 packets / 12s
tcpdump kernel dropped: 0
```

解释：

- `/video_feed` 会按约 30fps 持续吐 MJPEG。
- hash 变化率才更接近 decoded frame 更新频率。
- `/sniper_packets` 是 RTP packet 频率，不是视频帧率。
- 当前链路带宽很紧，40kbps 下能换到可接受的可见变化率和画面质量。

## Step-by-step Debugging

### 1. 确认没有旧进程混在一起

```bash
pgrep -af 'gst_e2e_sender|hik_camera_ros2_driver|rm_serial_driver|python3 app.py|ros2 launch rm_vision_bringup|ros2 run'
```

如果是 systemd 用户服务启动的：

```bash
systemctl --user --no-pager --full is-active \
  piny-serial.service \
  piny-camera.service \
  piny-sender.service \
  pinyclient-app-mqtt.service
```

需要停服务时：

```bash
systemctl --user stop \
  piny-serial.service \
  piny-camera.service \
  piny-sender.service \
  pinyclient-app-mqtt.service
```

如果是手动进程，用 `pgrep -af` 看到 PID 后再 `kill PID`。不要在不确认 PID 的情况下回滚代码或重启一堆无关服务。

### 2. 启动真实 bringup

```bash
cd /home/hpy/pioneer/hero
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rm_vision_bringup vision_bringup.launch.py
```

正常日志应包含：

```text
sniper_camera
Acquisition frame rate: 30.000000
Shared memory output enabled: name=/hik_camera_rgb

gst_e2e_sender
SHM opened
SHM trail-only updater enabled
framerate=10/1
bitrate=40
output_packet_rate_limit_hz=30
output: ROS2 /sniper_packets

rm_serial_driver
Sniper serial send rate: about 58 Hz
```

### 3. 启动 PinyClient MQTT 图传源

```bash
cd /home/hpy/pioneer/doorlock/PinyClient
python3 app.py \
  --video-source mqtt \
  --mqtt-host 192.168.12.1 \
  --mqtt-port 3333
```

正常日志应包含：

```text
MQTT: core client 正在连接MQTT服务器 192.168.12.1:3333
MQTT: core client 连接成功
测试配置：启用MQTT图传数据源
图传源已切换为 MQTT
Running on http://127.0.0.1:5000
```

### 4. 检查 `/sniper_packets`

```bash
cd /home/hpy/pioneer/doorlock/PinyClient
source /opt/ros/humble/setup.bash
source /home/hpy/pioneer/hero/install/setup.bash
timeout 8s ros2 topic hz /sniper_packets
```

当前正常值通常在 25-30Hz 左右。这个数是 300B RTP packet 频率，不是视频帧率。

### 5. 检查 MQTT 是否从选手端回来

抓 broker 到 PC 的 MQTT：

```bash
RUN_DIR=logs/mqtt_loss_check/$(date +%Y%m%d_%H%M%S)_manual_probe
mkdir -p "$RUN_DIR"
sudo timeout 12s tcpdump -i enp43s0 -s 0 -A \
  'tcp port 3333 and src host 192.168.12.1' \
  > "$RUN_DIR/tcpdump_broker_to_pc_ascii.log" \
  2> "$RUN_DIR/tcpdump.stderr.log"
```

统计 topic：

```bash
python3 - <<'PY'
from pathlib import Path
run_dir = sorted(Path("logs/mqtt_loss_check").glob("*_manual_probe"))[-1]
data = (run_dir / "tcpdump_broker_to_pc_ascii.log").read_bytes()
err = (run_dir / "tcpdump.stderr.log").read_text(errors="ignore")
for s in [b"CustomByteBlock", b"ByteBlock", b"GameStatus", b"RobotDynamicStatus"]:
    print(s.decode(), data.count(s))
print(err.splitlines()[-4:])
PY
```

如果 `GameStatus` 有、`CustomByteBlock` 为 0，问题通常不在 PinyClient Web，而在下位机/裁判系统/选手端自定义数据回流状态。之前重启电脑和机器人后，dummy 300B 探针从 `CustomByteBlock=0` 恢复到了有回包。

### 6. 检查 Web 是否只是重复旧帧

```bash
python3 - <<'PY'
import time, urllib.request, hashlib, statistics

resp = urllib.request.urlopen("http://127.0.0.1:5000/video_feed", timeout=8)
buf = b""
frames = []
start = time.time()
try:
    while time.time() - start < 10 and len(frames) < 320:
        chunk = resp.read(8192)
        if not chunk:
            break
        buf += chunk
        while True:
            a = buf.find(b"\xff\xd8")
            b = buf.find(b"\xff\xd9", a + 2) if a != -1 else -1
            if a == -1 or b == -1:
                buf = buf[-200000:]
                break
            jpg = buf[a:b + 2]
            frames.append((time.time(), len(jpg), hashlib.sha1(jpg).hexdigest()[:16]))
            buf = buf[b + 2:]
finally:
    resp.close()

uniq = len(set(h for _, _, h in frames))
print("frames", len(frames), "unique", uniq)
if len(frames) > 1:
    intervals = [(frames[i][0] - frames[i - 1][0]) * 1000 for i in range(1, len(frames))]
    changes = sum(1 for i in range(1, len(frames)) if frames[i][2] != frames[i - 1][2])
    dur = frames[-1][0] - frames[0][0]
    print("fps", (len(frames) - 1) / dur)
    print("changes", changes, "change_rate_hz_approx", changes / dur)
    print("avg_jpeg_bytes", sum(x[1] for x in frames) / len(frames))
    print("interval_p50_max", statistics.median(intervals), max(intervals))
PY
```

判断方式：

- `fps` 接近 29-30，但 `change_rate_hz_approx` 只有几 Hz：Flask/Web 在持续输出，但 `latest_frame` 更新较慢。
- 当前 10fps/40kbps/300 的真实环路，hash 变化约 7-9Hz 是可接受状态。
- 如果 `unique` 长时间接近 1，先看 MQTT `CustomByteBlock` 是否真的回来，再看 PinyClient 日志里的 `rx/push/frame/latest_age_ms`。

### 7. 常见问题定位

#### Web 没图

按顺序看：

1. `app.py` 是否用了 `--video-source mqtt`。
2. app 日志是否 `MQTT: core client 连接成功`。
3. app 日志是否 `图传源已切换为 MQTT`。
4. tcpdump 是否有 `CustomByteBlock`。
5. sender 是否真的在发 `/sniper_packets`。
6. `rm_serial_driver` 是否有 `/sniper_packets` 订阅者。

#### 有状态 topic，但没有 `CustomByteBlock`

这通常说明 PC 到 MQTT broker 的连接没问题，但自定义数据没有从下位机/裁判系统/选手端回流。可用 dummy 300B 包排除图像编码：

```bash
cd /home/hpy/pioneer/doorlock/PinyClient
source /opt/ros/humble/setup.bash
source /home/hpy/pioneer/hero/install/setup.bash
tools/send_five_sniper_packets.sh --count 50 --hz 50
```

同时用 tcpdump 或 `tools/custom_block_probe.py` 看是否收到 `CustomByteBlock`。如果 dummy 也收不到，而 `GameStatus` 正常，优先重启下位机/裁判系统/选手端链路。

#### Web 有图但变化很慢

核心判断：

- `/video_feed` HTTP fps 高，不代表真实画面更新高。
- 看 hash change rate。
- 看 sender 的 `out_packets`、`out_drops`、`avg_rtp_len`。
- 看 PinyClient 的 `rx/push/frame/latest_age_ms`。

根因通常是 30 个 300B RTP packet/s 的预算不足以承载高码率 H264。当前 180kbps 会让一帧拆成多个 RTP 包，真实视频时间推进变慢。40kbps 能让更多帧落在 packet budget 内。

#### 花屏严重

不要用任意丢弃编码后 RTP 包的方式降延迟。H264 有参考帧，丢中间包会破坏后续解码。优先方向：

- 降低 bitrate。
- 降低 sender fps。
- 缩短 keyframe interval。
- 减少画面细节，例如中心外灰度化。
- 保证 `tcpdump kernel dropped = 0`，再判断是否是真实链路丢包。

#### 打开 `enable_display` 但没窗口

`/gst_e2e_sender` 的 `enable_display` 只影响 sender 进程内 OpenCV 调试窗口。若通过 launch 或 systemd 在没有图形会话/没有 `DISPLAY` 的环境启动，窗口可能不会出现。真实调试 Web 图像优先看 `/video_feed`；需要本地 OpenCV 窗口时，确认：

```bash
echo $DISPLAY
xhost +local:
```

并在可显示的终端里直接运行 sender。

## Minimum Checklist Before Saying It Works

每次真实环路验证至少记录：

```text
1. camera log:
   sniper_camera acquisition_frame_rate = 30.0
   SHM /hik_camera_rgb enabled

2. sender log:
   fps = 10
   bitrate = 40
   output_size = 300
   SHM trail-only updater enabled
   out_drops = 0

3. ROS:
   ros2 topic hz /sniper_packets ~= 25-30Hz

4. MQTT tcpdump:
   CustomByteBlock > 0
   tcpdump kernel dropped = 0

5. Web:
   /video_feed HTTP fps ~= 29Hz
   hash change rate ~= 7-9Hz
```

如果没有跑真实下位机/裁判系统/选手端/MQTT 回流，只能说本地模拟通过，不能说比赛链路通过。
