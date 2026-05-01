import base64
import socket
import sys
import threading
import time
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Optional

import cv2
import gi
import numpy as np

gi.require_version('Gst', '1.0')
from gi.repository import Gst  # pyright: ignore[reportAttributeAccessIssue]

sys.path.append("..")  # 添加项目根目录到sys.path，方便导入模块

from .mqtt_client import RMMQTTClient
from models.message import NormalUDPPackage
from models.protocol import messages_pb2 as _pb
from tools.rm_logger import RMColorLogger

logger = RMColorLogger("UDPReceiver")

MAX_DGRAM = 65535  # UDP数据包最大长度
UDP_HEADER_SIZE = 8

CUSTOM_BLOCK_TOPIC = "CustomByteBlock"
CUSTOM_BLOCK_SIZE = 300
CUSTOM_BLOCK_SERIALIZED_INNER_SIZE = 297
CUSTOM_BLOCK_FIXED_WIRE_SIZES = (CUSTOM_BLOCK_SIZE,)
CUSTOM_BLOCK_SERIALIZED_INNER_SIZES = (CUSTOM_BLOCK_SERIALIZED_INNER_SIZE,)
CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES = (
    *CUSTOM_BLOCK_FIXED_WIRE_SIZES,
    *CUSTOM_BLOCK_SERIALIZED_INNER_SIZES,
)
CUSTOM_BLOCK_HEADER_SIZE = 2
CUSTOM_BLOCK_RESERVED_BEGIN = 33
CUSTOM_BLOCK_RESERVED_END = 54
CUSTOM_BLOCK_RESERVED_SIZE = CUSTOM_BLOCK_RESERVED_END - CUSTOM_BLOCK_RESERVED_BEGIN
CUSTOM_BLOCK_FIRST_PAYLOAD_BYTES = CUSTOM_BLOCK_RESERVED_BEGIN - CUSTOM_BLOCK_HEADER_SIZE
CUSTOM_BLOCK_MAX_PAYLOAD = (
    CUSTOM_BLOCK_SIZE - CUSTOM_BLOCK_HEADER_SIZE - CUSTOM_BLOCK_RESERVED_SIZE
)
CUSTOM_BLOCK_SERIALIZED_PREFIX = b"\x0a\xa9\x02"

RTP_QUEUE_MAXSIZE = 256
MQTT_STATS_LOG_INTERVAL_SEC = 1.0

Gst.init(None)  # 初始化GStreamer


@dataclass
class MqttDecodeStats:
    rx_packets: int = 0
    bad_packets: int = 0
    pushed_packets: int = 0
    decoded_frames: int = 0
    last_decoded_ts: float = 0.0
    mqtt_outer_pb_fixed: int = 0
    mqtt_raw_fixed: int = 0
    sender_serialized_direct: int = 0
    sender_serialized_nested: int = 0
    last_stats_ts: float = 0.0


class ImgSource:
    def __init__(self):
        # 帧缓冲区
        self.frame_buffer: dict[int, bytes] = {}
        self.frame_id: int = -1  # 当前帧编号
        self.total_length: int = 0  # 当前帧总字节数
        self.cur_length: int = 0  # 当前帧已接收字节数
        self.last_activity: float = time.time()  # 上次接收数据的时间

        # 线程控制
        self.running = False
        self.receive_thread: Optional[threading.Thread] = None

        # 存储最新完整帧
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_lock = threading.Lock()

        # 超时清理（防止死等丢包）
        self.timeout_threshold = 10.0

        # 每帧大小
        self.width = 100
        self.height = 75
        self.channels = 3
        self.expected_frame_size = self.width * self.height * self.channels

        # 使用cv调试显示
        self.cv_debug = False

    def _init_frame(self, frame_id: int, total_length: int):
        self.frame_id = frame_id
        self.frame_buffer.clear()
        self.total_length = total_length
        self.cur_length = 0
        self.last_activity = time.time()

    def _update_frame(self, chunk_id: int, chunk_data: bytes):
        if chunk_id not in self.frame_buffer:
            self.frame_buffer[chunk_id] = chunk_data
            self.cur_length += len(chunk_data)
            self.last_activity = time.time()

    def _check_timeout(self):
        if time.time() - self.last_activity > self.timeout_threshold and self.frame_id != -1:
            logger.warning(
                f"帧 {self.frame_id} 接收超时，重置状态，已接收 {self.cur_length}/{self.total_length} 字节"
            )
            self._init_frame(-1, 0)

    def _try_assemble_frame(self):
        if self.cur_length == self.total_length and self.total_length > 0:
            frame_data = b''.join(self.frame_buffer[i] for i in sorted(self.frame_buffer.keys()))
            try:
                frame = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                    (self.height, self.width, self.channels)
                )
                with self.frame_lock:
                    self.latest_frame = frame.copy()
                self._init_frame(-1, 0)
                return frame
            except Exception as e:
                logger.error(f"处理帧 {self.frame_id} 时发生错误: {e}")

            self.frame_id = -1
            return None
        return None

    def start(self):
        raise NotImplementedError("子类必须实现 start 方法")

    def stop(self):
        raise NotImplementedError("子类必须实现 stop 方法")

    def get_frame(self) -> Optional[np.ndarray]:
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
        return None

    def _receive_loop(self):
        raise NotImplementedError("子类必须实现 _recv_loop 方法")


class MqttImgSource:
    def __init__(self, mqtt: RMMQTTClient) -> None:
        self.running = False
        self.mqtt_client = mqtt

        self.decode_thread: Optional[threading.Thread] = None
        self.packet_queue: Queue[bytes] = Queue(maxsize=RTP_QUEUE_MAXSIZE)

        self.latest_frame: Optional[np.ndarray] = None
        self.latest_frame_updated_at: float = 0.0
        self.frame_lock = threading.Lock()
        self.pipeline_lock = threading.RLock()
        self.cv_debug = False
        self.stats = MqttDecodeStats(last_stats_ts=time.time())

        self.pipeline = Gst.parse_launch(
            "appsrc name=source is-live=true format=time do-timestamp=false "
            "caps=\"application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000\" ! "
            "rtpjitterbuffer latency=50 drop-on-latency=true ! "
            "rtph264depay ! "
            "h264parse ! "
            "avdec_h264 ! "
            "videoconvert ! "
            "video/x-raw,format=BGR ! "
            "appsink name=sink sync=false max-buffers=5 drop=true emit-signals=true"
        )

        self.appsrc = self.pipeline.get_by_name("source")
        self.appsink = self.pipeline.get_by_name("sink")
        if self.appsrc is None or self.appsink is None:
            raise RuntimeError("GStreamer pipeline 初始化失败：无法获取 appsrc/appsink")
        self.appsrc.set_property("block", False)
        self.appsink.connect("new-sample", self._on_new_sample)

        self.bus = self.pipeline.get_bus()
        self._raw_callback_registered = False

    @staticmethod
    def _normalize_payload(raw_data: object) -> Optional[bytes]:
        if raw_data is None:
            return None
        if isinstance(raw_data, bytes):
            return raw_data
        if isinstance(raw_data, bytearray):
            return bytes(raw_data)
        if isinstance(raw_data, str):
            try:
                return base64.b64decode(raw_data)
            except Exception:
                return None
        return None

    def _decode_custom_byte_block(self, raw_data: object) -> Optional[bytes]:
        payload = self._normalize_payload(raw_data)
        if payload is None:
            self.stats.bad_packets += 1
            return None

        # 固定包协议：前2字节小端长度，后面是RTP负载+填充。
        # 正常模式为300B；sender预序列化模式为297B内层固定包。
        if len(payload) not in CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES:
            self.stats.bad_packets += 1
            return None

        actual_len = payload[0] | (payload[1] << 8)
        max_payload = self._custom_block_max_payload(len(payload))
        if max_payload is None:
            self.stats.bad_packets += 1
            return None
        if actual_len == 0 or actual_len > max_payload:
            self.stats.bad_packets += 1
            return None

        if len(payload) not in CUSTOM_BLOCK_FIXED_WIRE_SIZES:
            start = CUSTOM_BLOCK_HEADER_SIZE
            return payload[start:start + actual_len]

        first_len = min(actual_len, CUSTOM_BLOCK_FIRST_PAYLOAD_BYTES)
        first = payload[CUSTOM_BLOCK_HEADER_SIZE:CUSTOM_BLOCK_HEADER_SIZE + first_len]
        remaining = actual_len - first_len
        if remaining <= 0:
            return first
        second = payload[CUSTOM_BLOCK_RESERVED_END:CUSTOM_BLOCK_RESERVED_END + remaining]
        return first + second

    @staticmethod
    def _custom_block_max_payload(packet_size: int) -> Optional[int]:
        if packet_size in CUSTOM_BLOCK_FIXED_WIRE_SIZES:
            return packet_size - CUSTOM_BLOCK_HEADER_SIZE - CUSTOM_BLOCK_RESERVED_SIZE
        if packet_size in CUSTOM_BLOCK_SERIALIZED_INNER_SIZES:
            return packet_size - CUSTOM_BLOCK_HEADER_SIZE
        return None

    def _register_raw_callback(self):
        if not self._raw_callback_registered:
            self.mqtt_client.add_raw_topic_callback(CUSTOM_BLOCK_TOPIC, self._on_raw_custom_byte_block)
            self._raw_callback_registered = True

    def _unregister_raw_callback(self):
        if self._raw_callback_registered:
            self.mqtt_client.remove_raw_topic_callback(CUSTOM_BLOCK_TOPIC, self._on_raw_custom_byte_block)
            self._raw_callback_registered = False

    def _drain_packet_queue(self):
        while True:
            try:
                _ = self.packet_queue.get_nowait()
            except Empty:
                break

    def _on_raw_custom_byte_block(self, payload: bytes):
        """处理 MQTT CustomByteBlock 载荷。
        
        官方系统发送 Protobuf 序列化的 CustomByteBlock，其中 data 字段承载
        300B 固定包。固定包内 [33:54) 是污染规避区，接收端会跳过后拼接。
        sender预序列化开关打开时，原始固定包本身也是一个 CustomByteBlock，
        内部承载更小的固定包。
        """
        raw_300b = self._extract_custom_byte_block_data(payload)
        if raw_300b is None:
            self.stats.bad_packets += 1
            self._log_stats()
            return

        rtp_data = self._decode_custom_byte_block(raw_300b)
        if rtp_data is None:
            self._log_stats()
            return

        self.stats.rx_packets += 1
        try:
            self.packet_queue.put_nowait(rtp_data)
        except Full:
            try:
                _ = self.packet_queue.get_nowait()
            except Empty:
                pass
            try:
                self.packet_queue.put_nowait(rtp_data)
            except Full:
                pass
        self._log_stats()

    def _extract_custom_byte_block_data(self, payload: bytes) -> Optional[bytes]:
        """从 MQTT payload 中提取固定包数据。
        
        优先尝试 Protobuf 反序列化（官方格式），
        若失败且长度为固定包大小则视为原始格式（兼容模式）。
        """
        if payload is None:
            return None

        # 尝试 Protobuf 反序列化
        try:
            pb_msg = _pb.CustomByteBlock()
            pb_msg.ParseFromString(payload)
            nested = MqttImgSource._extract_nested_custom_byte_block_data(pb_msg.data)
            if nested is not None:
                self.stats.sender_serialized_nested += 1
                return nested
            if len(pb_msg.data) in CUSTOM_BLOCK_SERIALIZED_INNER_SIZES:
                self.stats.sender_serialized_direct += 1
                return pb_msg.data
            if len(pb_msg.data) in CUSTOM_BLOCK_FIXED_WIRE_SIZES:
                self.stats.mqtt_outer_pb_fixed += 1
                return pb_msg.data
        except Exception:
            pass

        # 兼容模式：原始固定包字节
        if len(payload) in CUSTOM_BLOCK_FIXED_WIRE_SIZES:
            nested = MqttImgSource._extract_nested_custom_byte_block_data(payload)
            if nested is not None:
                self.stats.sender_serialized_direct += 1
                return nested
            self.stats.mqtt_raw_fixed += 1
            return payload

        return None

    @staticmethod
    def _extract_nested_custom_byte_block_data(payload: bytes) -> Optional[bytes]:
        if len(payload) not in CUSTOM_BLOCK_FIXED_WIRE_SIZES:
            return None
        if not payload.startswith(CUSTOM_BLOCK_SERIALIZED_PREFIX):
            return None
        try:
            nested_msg = _pb.CustomByteBlock()
            nested_msg.ParseFromString(payload)
            if len(nested_msg.data) in CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES:
                return nested_msg.data
        except Exception:
            return None
        return None

    def _push_rtp_data(self, rtp_data: bytes) -> bool:
        if not rtp_data:
            return False

        buf = Gst.Buffer.new_allocate(None, len(rtp_data), None)
        buf.fill(0, rtp_data)

        with self.pipeline_lock:
            ret = self.appsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            logger.debug(f"RTP推送失败: {ret}")
            return False
        return True

    @staticmethod
    def _wall_clock_ms(ts: Optional[float] = None) -> str:
        if ts is None:
            ts = time.time()
        millis = int((ts - int(ts)) * 1000)
        return f"{time.strftime('%H:%M:%S', time.localtime(ts))}.{millis:03d}"

    @staticmethod
    def _draw_receiver_overlay(frame: np.ndarray, decoded_idx: int, ts: float):
        text = f"RX {MqttImgSource._wall_clock_ms(ts)} D{decoded_idx}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.42 if frame.shape[1] >= 300 else 0.35
        thickness = 1
        (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
        x = 6
        y = max(text_h + 8, frame.shape[0] - 8)
        x1 = max(0, x - 3)
        y1 = max(0, y - text_h - 5)
        x2 = min(frame.shape[1], x + text_w + 5)
        y2 = min(frame.shape[0], y + baseline + 5)
        if x2 > x1 and y2 > y1:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 0), -1)
        cv2.putText(frame, text, (x, y), font, scale, (0, 255, 255), thickness, cv2.LINE_AA)

    def _on_new_sample(self, sink):
        try:
            sample = sink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.OK

            buf = sample.get_buffer()
            caps = sample.get_caps()
            if buf is None or caps is None:
                return Gst.FlowReturn.OK

            caps_struct = caps.get_structure(0)
            width = caps_struct.get_value("width")
            height = caps_struct.get_value("height")
            if not isinstance(width, int) or not isinstance(height, int):
                return Gst.FlowReturn.OK

            ok, map_info = buf.map(Gst.MapFlags.READ)
            if not ok:
                return Gst.FlowReturn.OK

            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
            buf.unmap(map_info)

            decoded_idx = self.stats.decoded_frames + 1
            decoded_ts = time.time()
            self._draw_receiver_overlay(frame, decoded_idx, decoded_ts)

            with self.frame_lock:
                self.latest_frame = frame
                self.latest_frame_updated_at = decoded_ts
            self.stats.decoded_frames = decoded_idx
            self.stats.last_decoded_ts = decoded_ts

            if self.cv_debug:
                cv2.imshow("MQTT Stream", frame)
                cv2.waitKey(1)
        except Exception as e:
            logger.debug(f"new-sample 处理异常: {e}")

        return Gst.FlowReturn.OK

    def _log_stats(self):
        now = time.time()
        if now - self.stats.last_stats_ts < MQTT_STATS_LOG_INTERVAL_SEC:
            return
        with self.frame_lock:
            latest_frame_updated_at = self.latest_frame_updated_at
        latest_age_ms = (
            (now - latest_frame_updated_at) * 1000.0
            if latest_frame_updated_at > 0
            else -1.0
        )
        logger.debug(
            (
                "MQTT解码统计: rx=%d bad=%d push=%d frame=%d queue=%d latest_age_ms=%.1f "
                "outer_pb_fixed=%d raw_fixed=%d sender_direct=%d sender_nested=%d"
            ),
            self.stats.rx_packets,
            self.stats.bad_packets,
            self.stats.pushed_packets,
            self.stats.decoded_frames,
            self.packet_queue.qsize(),
            latest_age_ms,
            self.stats.mqtt_outer_pb_fixed,
            self.stats.mqtt_raw_fixed,
            self.stats.sender_serialized_direct,
            self.stats.sender_serialized_nested,
        )
        self.stats.last_stats_ts = now

    def _poll_bus(self):
        with self.pipeline_lock:
            while True:
                msg = self.bus.pop_filtered(
                    Gst.MessageType.ERROR | Gst.MessageType.WARNING | Gst.MessageType.EOS
                )
                if msg is None:
                    break

                if msg.type == Gst.MessageType.ERROR:
                    err, dbg = msg.parse_error()
                    logger.error(f"MQTT解码器错误: {err}, debug={dbg}")
                elif msg.type == Gst.MessageType.WARNING:
                    warn, dbg = msg.parse_warning()
                    logger.warning(f"MQTT解码器警告: {warn}, debug={dbg}")
                elif msg.type == Gst.MessageType.EOS:
                    logger.warning("MQTT解码器收到EOS")
                    self.running = False

    def reset_decoder(self):
        """重置 H264 RTP 解码器，清掉旧参考帧和队列。"""
        self._drain_packet_queue()
        with self.frame_lock:
            self.latest_frame = None
            self.latest_frame_updated_at = 0.0
        with self.pipeline_lock:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_state(Gst.SECOND)
            self.pipeline.set_state(Gst.State.PLAYING)
            self.pipeline.get_state(Gst.SECOND)
        self._drain_packet_queue()
        logger.info("MQTT H264解码器已重置")

    def _decode_loop(self):
        while self.running:
            self._poll_bus()

            try:
                rtp_data = self.packet_queue.get(timeout=0.05)
                if self._push_rtp_data(rtp_data):
                    self.stats.pushed_packets += 1
            except Empty:
                pass
            except Exception as e:
                logger.error(f"RTP 推流异常: {e}")

            self._log_stats()
            time.sleep(0.001)

    def start(self):
        if self.running:
            logger.warning("MQTT UDP服务器已经在运行")
            return

        self._drain_packet_queue()
        self._register_raw_callback()

        with self.pipeline_lock:
            self.pipeline.set_state(Gst.State.PLAYING)
        self.running = True

        self.decode_thread = threading.Thread(target=self._decode_loop, daemon=True)
        self.decode_thread.start()
        logger.info("MQTT UDP服务器解码线程已启动")

    def stop(self):
        if not self.running:
            logger.warning("MQTT UDP服务器已经停止")
            return

        self.running = False

        if self.decode_thread is not None:
            self.decode_thread.join(timeout=5.0)
        logger.info("MQTT UDP服务器解码线程已停止")

        with self.pipeline_lock:
            self.appsrc.emit("end-of-stream")
            self.pipeline.set_state(Gst.State.NULL)
        self._unregister_raw_callback()
        logger.info("MQTT 管道解码器已结束进程")

    def get_frame(self) -> Optional[np.ndarray]:
        with self.frame_lock:
            return None if self.latest_frame is None else self.latest_frame.copy()


class NormalImgSource(ImgSource):
    def __init__(self, host: str = "127.0.0.1", port: int = 3334) -> None:
        super().__init__()
        self._bind_host = host
        self._bind_port = port
        self.decode_thread: Optional[threading.Thread] = None
        self.packet_queue: Queue[bytes] = Queue(maxsize=RTP_QUEUE_MAXSIZE)
        self.sock: Optional[socket.socket] = None
        self._create_and_bind_socket()

        self.pipeline = Gst.parse_launch(
            "appsrc name=hevc_source is-live=true format=time do-timestamp=false "
            "caps=\"video/x-h265,stream-format=byte-stream,alignment=au\" ! "
            "h265parse ! avdec_h265 ! videoconvert ! video/x-raw,format=BGR ! "
            "appsink name=hevc_sink sync=false max-buffers=5 drop=true emit-signals=true"
        )
        self.appsrc = self.pipeline.get_by_name("hevc_source")
        self.appsink = self.pipeline.get_by_name("hevc_sink")
        if self.appsrc is None or self.appsink is None:
            raise RuntimeError("GStreamer HEVC pipeline 初始化失败：无法获取 appsrc/appsink")

        self.appsrc.set_property("block", False)
        self.appsink.connect("new-sample", self._on_hevc_new_sample)
        self.bus = self.pipeline.get_bus()

    def _create_and_bind_socket(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind((self._bind_host, self._bind_port))
        except Exception as e:
            self.sock.close()
            self.sock = None
            raise RuntimeError(
                f"无法绑定UDP端口 {self._bind_host}:{self._bind_port}，该端口可能已被其他进程占用。错误信息: {e}"
            )
        self.sock.settimeout(1.0)
        logger.info(f"UDP接收器已绑定到 {self.sock.getsockname()}")

    def _drain_packet_queue(self):
        while True:
            try:
                _ = self.packet_queue.get_nowait()
            except Empty:
                break

    def _try_assemble_frame(self):
        if self.cur_length == self.total_length and self.total_length > 0:
            frame_data = b''.join(self.frame_buffer[i] for i in sorted(self.frame_buffer.keys()))

            try:
                self.packet_queue.put_nowait(frame_data)
            except Full:
                try:
                    _ = self.packet_queue.get_nowait()
                except Empty:
                    pass
                try:
                    self.packet_queue.put_nowait(frame_data)
                except Full:
                    pass

            self._init_frame(-1, 0)
            return None

        return None

    def _push_hevc_data(self, hevc_data: bytes) -> bool:
        if not hevc_data:
            return False

        buf = Gst.Buffer.new_allocate(None, len(hevc_data), None)
        buf.fill(0, hevc_data)
        ret = self.appsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            logger.debug(f"HEVC推送失败: {ret}")
            return False
        return True

    def _on_hevc_new_sample(self, sink):
        try:
            sample = sink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.OK

            buf = sample.get_buffer()
            caps = sample.get_caps()
            if buf is None or caps is None:
                return Gst.FlowReturn.OK

            caps_struct = caps.get_structure(0)
            width = caps_struct.get_value("width")
            height = caps_struct.get_value("height")
            if not isinstance(width, int) or not isinstance(height, int):
                return Gst.FlowReturn.OK

            ok, map_info = buf.map(Gst.MapFlags.READ)
            if not ok:
                return Gst.FlowReturn.OK

            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
            buf.unmap(map_info)

            with self.frame_lock:
                self.latest_frame = frame

            if self.cv_debug:
                cv2.imshow("UDP HEVC Stream", frame)
                cv2.waitKey(1)
        except Exception as e:
            logger.debug(f"HEVC new-sample 处理异常: {e}")

        return Gst.FlowReturn.OK

    def _poll_bus(self):
        while True:
            msg = self.bus.pop_filtered(
                Gst.MessageType.ERROR | Gst.MessageType.WARNING | Gst.MessageType.EOS
            )
            if msg is None:
                break

            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                logger.error(f"UDP HEVC解码器错误: {err}, debug={dbg}")
            elif msg.type == Gst.MessageType.WARNING:
                warn, dbg = msg.parse_warning()
                logger.warning(f"UDP HEVC解码器警告: {warn}, debug={dbg}")
            elif msg.type == Gst.MessageType.EOS:
                logger.warning("UDP HEVC解码器收到EOS")

    def _decode_loop(self):
        while self.running:
            self._poll_bus()

            try:
                hevc_data = self.packet_queue.get(timeout=0.05)
                self._push_hevc_data(hevc_data)
            except Empty:
                pass
            except Exception as e:
                logger.error(f"HEVC 推流异常: {e}")

            time.sleep(0.001)

    def _receive_loop(self):
        if self.sock is None:
            logger.error("UDP socket 未初始化，无法启动接收循环")
            return

        logger.info(f"3334 UDP接收循环已启动，监听{self.sock.getsockname()}，等待数据包...")
        while self.running:
            try:
                data, addr = self.sock.recvfrom(MAX_DGRAM)

                if len(data) < UDP_HEADER_SIZE:
                    logger.warning("此数据包无效，忽略")
                    continue

                frame_id, chunk_id, total_length = NormalUDPPackage(data=data).parse()[:3]
                chunk_data = data[UDP_HEADER_SIZE:]
                # [RM 2026 协议适配] 严格遵循官方文档：UDP 3334 端口前 8 字节为自定义分片头，后续才是 HEVC 裸流。
                # 必须剥离 8 字节头后再喂给 GStreamer 的 appsrc，否则 h265parse 会因找不到 NALU 起始码而黑屏。

                self._check_timeout()

                if frame_id != self.frame_id:
                    if self.frame_id != -1:
                        logger.debug(
                            f"接收到新帧 {frame_id}，当前帧 {self.frame_id} 已完成接收，尝试拼接上一帧"
                        )
                        self._try_assemble_frame()
                    self._init_frame(frame_id, total_length)

                self._update_frame(chunk_id, chunk_data)
                self._try_assemble_frame()
            except socket.timeout:
                self._check_timeout()
                continue
            except Exception as e:
                logger.error(f"接收数据包时发生错误: {e}")
        logger.info("UDP服务器已停止")

    def start(self):
        if self.running:
            logger.warning("UDP服务器已经在运行")
            return

        if self.sock is None:
            self._create_and_bind_socket()

        try:
            bound_host, bound_port = self.sock.getsockname() # pyright: ignore[reportOptionalMemberAccess]
        except OSError:
            self._create_and_bind_socket()
            bound_host, bound_port = self.sock.getsockname() # pyright: ignore[reportOptionalMemberAccess]
        if bound_port != self._bind_port:
            raise RuntimeError(
                f"UDP套接字绑定异常，期望端口 {self._bind_port}，实际 {bound_host}:{bound_port}"
            )

        self._drain_packet_queue()
        self.pipeline.set_state(Gst.State.PLAYING)
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.decode_thread = threading.Thread(target=self._decode_loop, daemon=True)
        
        self.receive_thread.start()
        self.decode_thread.start()
        logger.info("UDP服务器线程与HEVC解码线程已启动")

    def stop(self):
        if not self.running:
            logger.warning("UDP服务器已经停止")
            return
        self.running = False

        if self.receive_thread is not None:
            self.receive_thread.join(timeout=5.0)
        if self.decode_thread is not None:
            self.decode_thread.join(timeout=5.0)

        self.appsrc.emit("end-of-stream")
        self.pipeline.set_state(Gst.State.NULL)
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        self.receive_thread = None
        self.decode_thread = None
        logger.info("UDP服务器线程已停止")


if __name__ == "__main__":
    pass
