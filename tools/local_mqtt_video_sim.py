#!/usr/bin/env python3
"""Local end-to-end MQTT video simulator.

Flow:
  hik_camera_ros2_driver SHM or video file
    -> gst_e2e_sender ROS2 sniper_packets
    -> real rm_serial_driver 5-piece serial split
    -> virtual lower-computer reassembly
    -> MQTT CustomByteBlock protobuf
    -> PinyClient web /video_feed
"""

from __future__ import annotations

import argparse
import os
import pty
import re
import signal
import select
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tty
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

warnings.filterwarnings(
    "ignore",
    message="Callback API version 1 is deprecated.*",
    category=DeprecationWarning,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.protocol import messages_pb2 as pb  # noqa: E402


CUSTOM_BLOCK_TOPIC = "CustomByteBlock"
CUSTOM_BLOCK_SIZE = 300
CUSTOM_BLOCK_SERIALIZED_INNER_SIZE = 297
CUSTOM_BLOCK_SERIALIZED_PREFIX = b"\x0a\xa9\x02"
CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES = (CUSTOM_BLOCK_SIZE, CUSTOM_BLOCK_SERIALIZED_INNER_SIZE)

SNIPER_SUB_HEADERS = (0xA6, 0xA7, 0xA8, 0xA9, 0xAA)
SNIPER_SUB_DATA_SIZE = 60
SNIPER_SUB_PACKET_SIZE = 63
SNIPER_TOTAL_DATA = 300
CRC16_INIT = 0xFFFF
CRC16_POLY_REVERSED = 0x8408
SHM_MAGIC = 0x314D4853
PLAYLIST_DRAIN_IDLE_SEC = 0.4
PLAYLIST_DRAIN_TIMEOUT_SEC = 3.0


@dataclass
class BridgeStats:
    udp_300_rx: int = 0
    udp_bad_size: int = 0
    serial_rx_bytes: int = 0
    serial_noise_bytes: int = 0
    serial_sub_packets: int = 0
    crc_ok: int = 0
    crc_bad: int = 0
    serial_bad_groups: int = 0
    reassembled_300: int = 0
    serialized_inner_297: int = 0
    nested_serialized_inner_297: int = 0
    mqtt_published: int = 0
    mqtt_publish_failed: int = 0
    rtp_packets: int = 0
    rtp_bad_packets: int = 0
    rtp_frames: int = 0
    rtp_payload_bytes: int = 0


def log(message: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"{ts} | local-sim | {message}", flush=True)


def summarize_numbers(values: list[int]) -> str:
    if not values:
        return "n/a"
    return f"min={min(values)} max={max(values)} avg={sum(values) / len(values):.1f}"


def crc16_referee(data: bytes, init: int = CRC16_INIT) -> int:
    """Same CRC16 variant used by rm_serial_driver/crc.cpp."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ CRC16_POLY_REVERSED
            else:
                crc >>= 1
            crc &= 0xFFFF
    return crc & 0xFFFF


def append_crc16(data_without_crc: bytes) -> bytes:
    crc = crc16_referee(data_without_crc)
    return data_without_crc + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def verify_crc16(packet: bytes) -> bool:
    if len(packet) <= 2:
        return False
    expected = crc16_referee(packet[:-2])
    return packet[-2] == (expected & 0xFF) and packet[-1] == ((expected >> 8) & 0xFF)


def build_serialized_custom_block_packet(rtp_payload: bytes) -> bytes:
    max_payload = CUSTOM_BLOCK_SERIALIZED_INNER_SIZE - 2
    if len(rtp_payload) > max_payload:
        raise ValueError(f"serialized sender RTP payload must be <= {max_payload} bytes")

    inner = bytearray(CUSTOM_BLOCK_SERIALIZED_INNER_SIZE)
    struct.pack_into("<H", inner, 0, len(rtp_payload))
    inner[2:2 + len(rtp_payload)] = rtp_payload
    return CUSTOM_BLOCK_SERIALIZED_PREFIX + bytes(inner)


def extract_serialized_custom_block(payload: bytes) -> Optional[bytes]:
    if len(payload) != CUSTOM_BLOCK_SIZE or not payload.startswith(CUSTOM_BLOCK_SERIALIZED_PREFIX):
        return None
    try:
        msg = pb.CustomByteBlock()
        msg.ParseFromString(payload)
    except Exception:
        return None
    if len(msg.data) in CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES:
        return msg.data
    return None


def extract_fixed_packet_payload(payload: bytes) -> Optional[bytes]:
    nested = extract_serialized_custom_block(payload)
    if nested is not None:
        payload = nested

    if len(payload) not in CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES:
        return None
    actual_len = payload[0] | (payload[1] << 8)
    if actual_len <= 0 or actual_len > len(payload) - 2:
        return None
    return payload[2:2 + actual_len]


def build_sniper_sub_packets(payload: bytes) -> list[bytes]:
    if len(payload) != SNIPER_TOTAL_DATA:
        raise ValueError(f"sniper payload must be 300 bytes, got {len(payload)}")

    packets: list[bytes] = []
    for idx, header in enumerate(SNIPER_SUB_HEADERS):
        start = idx * SNIPER_SUB_DATA_SIZE
        end = start + SNIPER_SUB_DATA_SIZE
        body = bytes((header,)) + payload[start:end]
        packets.append(append_crc16(body))
    return packets


class SniperSerialReassembler:
    """Simulates the lower-computer side of the 5-piece serial contract."""

    def __init__(self) -> None:
        self._chunks: dict[int, bytes] = {}

    def feed(self, sub_packet: bytes) -> Optional[bytes]:
        if len(sub_packet) != SNIPER_SUB_PACKET_SIZE:
            raise ValueError(f"serial sub-packet must be 63 bytes, got {len(sub_packet)}")
        if not verify_crc16(sub_packet):
            raise ValueError(f"serial sub-packet CRC error, header=0x{sub_packet[0]:02X}")

        header = sub_packet[0]
        if header not in SNIPER_SUB_HEADERS:
            raise ValueError(f"unexpected serial sub-packet header: 0x{header:02X}")

        index = SNIPER_SUB_HEADERS.index(header)
        if index == 0:
            self._chunks.clear()

        self._chunks[index] = sub_packet[1:1 + SNIPER_SUB_DATA_SIZE]
        if len(self._chunks) != len(SNIPER_SUB_HEADERS):
            return None

        reassembled = b"".join(self._chunks[i] for i in range(len(SNIPER_SUB_HEADERS)))
        self._chunks.clear()
        return reassembled


def encode_custom_byte_block(payload_300: bytes) -> bytes:
    if len(payload_300) != CUSTOM_BLOCK_SIZE:
        raise ValueError(f"CustomByteBlock.data must be 300 bytes, got {len(payload_300)}")
    msg = pb.CustomByteBlock()
    msg.data = payload_300
    return msg.SerializeToString()


def create_mqtt_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
    except AttributeError:
        return mqtt.Client(client_id=client_id)


class MqttPublisher:
    def __init__(self, host: str, port: int, client_id: str, topic: str) -> None:
        self.host = host
        self.port = port
        self.topic = topic
        self.client = create_mqtt_client(client_id)
        self._connected = threading.Event()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, _client, _userdata, _flags, rc) -> None:
        if rc == 0:
            self._connected.set()
            log(f"MQTT publisher connected to {self.host}:{self.port}")
        else:
            log(f"MQTT publisher connect failed, rc={rc}")

    def _on_disconnect(self, _client, _userdata, rc) -> None:
        self._connected.clear()
        if rc != 0:
            log(f"MQTT publisher disconnected unexpectedly, rc={rc}")

    def start(self) -> None:
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        if not self._connected.wait(timeout=5.0):
            raise RuntimeError(f"MQTT publisher connect timeout: {self.host}:{self.port}")

    def publish_custom_block(self, payload_300: bytes) -> bool:
        payload = encode_custom_byte_block(payload_300)
        info = self.client.publish(self.topic, payload, qos=0)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()


def build_init_packet() -> bytes:
    """ReceivePacket fed to rm_serial_driver so its receive thread stays healthy."""
    packet = bytearray(20)
    packet[0] = 0x5A
    packet[1] = 0x00
    struct.pack_into("<f", packet, 2, 0.0)
    struct.pack_into("<f", packet, 6, 0.0)
    struct.pack_into("<f", packet, 10, 0.0)
    struct.pack_into("<f", packet, 14, 15.0)
    crc = crc16_referee(bytes(packet[:18]))
    struct.pack_into("<H", packet, 18, crc)
    return bytes(packet)


@dataclass
class ManagedProcess:
    name: str
    proc: subprocess.Popen

    def is_running(self) -> bool:
        return self.proc.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        if self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGINT)
            self.proc.wait(timeout=timeout)
        except Exception:
            if self.proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                    self.proc.wait(timeout=2.0)
                except Exception:
                    if self.proc.poll() is None:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                        self.proc.wait(timeout=2.0)


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def ros_shell_command(args: argparse.Namespace, command: list[str]) -> list[str]:
    setup_parts: list[str] = []
    if args.ros_distro_setup:
        setup_parts.append(f"source {shlex.quote(str(args.ros_distro_setup))}")
    setup_parts.append(f"source {shlex.quote(str(args.ros_setup))}")
    return ["bash", "-lc", " && ".join(setup_parts) + " && exec " + shell_join(command)]


def start_managed_process(
    name: str,
    command: list[str],
    args: argparse.Namespace,
    quiet: bool = False,
) -> ManagedProcess:
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.STDOUT if quiet else None
    log(f"starting {name}: " + shell_join(command))
    proc = subprocess.Popen(
        ros_shell_command(args, command),
        cwd=str(args.hero_root),
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    return ManagedProcess(name=name, proc=proc)


def shm_path(shm_name: str) -> Path:
    return Path("/dev/shm") / shm_name.lstrip("/")


def read_shm_sequence(shm_name: str) -> Optional[int]:
    path = shm_path(shm_name)
    try:
        with path.open("rb") as fp:
            header = fp.read(16)
    except OSError:
        return None
    if len(header) < 16:
        return None
    magic, _version, sequence = struct.unpack("<IIQ", header)
    if magic != SHM_MAGIC:
        return None
    return sequence


def wait_for_shm(shm_name: str, timeout: float, initial_sequence: Optional[int]) -> bool:
    path = shm_path(shm_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            sequence = read_shm_sequence(shm_name)
            if sequence is not None and sequence != initial_sequence:
                return True
        time.sleep(0.1)
    return False


def create_serial_params_file(args: argparse.Namespace, slave_name: str) -> Path:
    content = f"""/rm_serial_driver:
  ros__parameters:
    device_name: "{slave_name}"
    baud_rate: {args.serial_baud_rate}
    flow_control: "none"
    parity: "none"
    stop_bits: "1"
    timestamp_offset: 0.006
    sniper_send_rate_hz: {args.serial_send_rate}
"""
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="piny_serial_",
        suffix=".yaml",
        delete=False,
    ) as fp:
        fp.write(content)
        return Path(fp.name)


class PtyMqttBridge:
    """MCU-side simulator: read real rm_serial_driver serial bytes and publish MQTT."""

    def __init__(
        self,
        master_fd: int,
        publisher: MqttPublisher,
        stats_interval: float,
        init_interval: float,
    ) -> None:
        self.master_fd = master_fd
        self.publisher = publisher
        self.stats_interval = stats_interval
        self.init_interval = init_interval
        self.stats = BridgeStats()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._init_packet = build_init_packet()
        self._interval_start = time.monotonic()
        self._interval_effective_lengths: list[int] = []
        self._interval_frame_packet_counts: list[int] = []
        self._interval_frame_bytes: list[int] = []
        self._current_rtp_ts: Optional[int] = None
        self._current_frame_packets = 0
        self._current_frame_bytes = 0
        self._expected_sub_index = 0
        self._reassembly_payload = bytearray(SNIPER_TOTAL_DATA)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="pty-mqtt-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def send_init_packet(self) -> None:
        try:
            os.write(self.master_fd, self._init_packet)
        except OSError:
            pass

    def _loop(self) -> None:
        buffer = b""
        last_stats = time.monotonic()
        last_init = 0.0

        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_init >= self.init_interval:
                self.send_init_packet()
                last_init = now

            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.05)
                if not ready:
                    if self._maybe_log_stats(last_stats):
                        last_stats = time.monotonic()
                    continue
                chunk = os.read(self.master_fd, 8192)
            except OSError:
                break

            if not chunk:
                continue

            self.stats.serial_rx_bytes += len(chunk)
            buffer += chunk
            buffer = self._consume_buffer(buffer)

            if self._maybe_log_stats(last_stats):
                last_stats = time.monotonic()

    def _reset_serial_reassembly(self) -> None:
        self._expected_sub_index = 0
        self._reassembly_payload = bytearray(SNIPER_TOTAL_DATA)

    def _consume_buffer(self, buffer: bytes) -> bytes:
        while buffer:
            expected_header = SNIPER_SUB_HEADERS[self._expected_sub_index]
            expected_pos = buffer.find(bytes((expected_header,)))

            if self._expected_sub_index > 0:
                restart_pos = buffer.find(bytes((SNIPER_SUB_HEADERS[0],)))
                if restart_pos != -1 and (expected_pos == -1 or restart_pos < expected_pos):
                    if restart_pos > 0:
                        self.stats.serial_noise_bytes += restart_pos
                        buffer = buffer[restart_pos:]
                    self.stats.serial_bad_groups += 1
                    self._reset_serial_reassembly()
                    continue

            if expected_pos == -1:
                self.stats.serial_noise_bytes += len(buffer)
                return b""

            if expected_pos > 0:
                self.stats.serial_noise_bytes += expected_pos
                buffer = buffer[expected_pos:]

            if len(buffer) < SNIPER_SUB_PACKET_SIZE:
                return buffer

            sub_packet = buffer[:SNIPER_SUB_PACKET_SIZE]
            if sub_packet[0] != expected_header or not verify_crc16(sub_packet):
                if sub_packet[0] == expected_header:
                    self.stats.crc_bad += 1
                self.stats.serial_bad_groups += 1
                buffer = buffer[1:]
                continue

            buffer = buffer[SNIPER_SUB_PACKET_SIZE:]
            payload_offset = self._expected_sub_index * SNIPER_SUB_DATA_SIZE
            self._reassembly_payload[
                payload_offset:payload_offset + SNIPER_SUB_DATA_SIZE
            ] = sub_packet[1:1 + SNIPER_SUB_DATA_SIZE]
            self.stats.serial_sub_packets += 1
            self.stats.crc_ok += 1

            self._expected_sub_index += 1
            if self._expected_sub_index < len(SNIPER_SUB_HEADERS):
                continue

            payload_300 = bytes(self._reassembly_payload)
            self._reset_serial_reassembly()

            self.stats.reassembled_300 += 1
            if extract_serialized_custom_block(payload_300) is not None:
                self.stats.serialized_inner_297 += 1
            self._record_rtp_packet(payload_300)
            if self.publisher.publish_custom_block(payload_300):
                self.stats.mqtt_published += 1
            else:
                self.stats.mqtt_publish_failed += 1

        return buffer

    def _record_rtp_packet(self, payload_300: bytes) -> None:
        payload = extract_serialized_custom_block(payload_300)
        if payload is not None:
            self.stats.nested_serialized_inner_297 += 1
        else:
            payload = payload_300

        if len(payload) not in CUSTOM_BLOCK_SUPPORTED_FIXED_SIZES:
            self.stats.rtp_bad_packets += 1
            return

        actual_len = payload[0] | (payload[1] << 8)
        if actual_len <= 0 or actual_len > len(payload) - 2:
            self.stats.rtp_bad_packets += 1
            return

        rtp = payload[2:2 + actual_len]
        if len(rtp) < 12:
            self.stats.rtp_bad_packets += 1
            return

        marker = bool(rtp[1] & 0x80)
        timestamp = int.from_bytes(rtp[4:8], "big")

        self.stats.rtp_packets += 1
        self.stats.rtp_payload_bytes += actual_len
        self._interval_effective_lengths.append(actual_len)

        if self._current_rtp_ts is None:
            self._current_rtp_ts = timestamp
        elif timestamp != self._current_rtp_ts:
            self._finish_rtp_frame()
            self._current_rtp_ts = timestamp

        self._current_frame_packets += 1
        self._current_frame_bytes += actual_len

        if marker:
            self._finish_rtp_frame()
            self._current_rtp_ts = None

    def _finish_rtp_frame(self) -> None:
        if self._current_frame_packets <= 0:
            return
        self.stats.rtp_frames += 1
        self._interval_frame_packet_counts.append(self._current_frame_packets)
        self._interval_frame_bytes.append(self._current_frame_bytes)
        self._current_frame_packets = 0
        self._current_frame_bytes = 0

    def _group_is_valid(self, sub_packets: list[bytes]) -> bool:
        for index, packet in enumerate(sub_packets):
            if len(packet) != SNIPER_SUB_PACKET_SIZE:
                return False
            if packet[0] != SNIPER_SUB_HEADERS[index]:
                return False
            if not verify_crc16(packet):
                self.stats.crc_bad += 1
                return False
        return True

    def _maybe_log_stats(self, last_stats: float) -> bool:
        if time.monotonic() - last_stats < self.stats_interval:
            return False
        elapsed = max(time.monotonic() - self._interval_start, 1e-6)
        frame_fps = len(self._interval_frame_packet_counts) / elapsed
        effective_summary = summarize_numbers(self._interval_effective_lengths)
        frame_bytes_summary = summarize_numbers(self._interval_frame_bytes)
        frame_packet_summary = summarize_numbers(self._interval_frame_packet_counts)
        log(
            "stats "
            f"serial_rx_bytes={self.stats.serial_rx_bytes} "
            f"serial_noise_bytes={self.stats.serial_noise_bytes} "
            f"serial_sub_packets={self.stats.serial_sub_packets} "
            f"crc_ok={self.stats.crc_ok} "
            f"crc_bad={self.stats.crc_bad} "
            f"serial_bad_groups={self.stats.serial_bad_groups} "
            f"reassembled_300={self.stats.reassembled_300} "
            f"serialized_inner_297={self.stats.serialized_inner_297} "
            f"mqtt_published={self.stats.mqtt_published} "
            f"mqtt_publish_failed={self.stats.mqtt_publish_failed} "
            f"rtp_packets={self.stats.rtp_packets} "
            f"rtp_frames={self.stats.rtp_frames} "
            f"frame_fps={frame_fps:.1f} "
            f"effective_rtp_len_in_300B=({effective_summary}) "
            f"frame_rtp_bytes=({frame_bytes_summary}) "
            f"rtp_packets_per_frame=({frame_packet_summary})"
        )
        self._interval_start = time.monotonic()
        self._interval_effective_lengths.clear()
        self._interval_frame_packet_counts.clear()
        self._interval_frame_bytes.clear()
        return True


class SerialMqttBridge:
    def __init__(
        self,
        udp_bind_host: str,
        udp_port: int,
        publisher: MqttPublisher,
        stats_interval: float,
    ) -> None:
        self.udp_bind_host = udp_bind_host
        self.udp_port = udp_port
        self.publisher = publisher
        self.stats_interval = stats_interval
        self.stats = BridgeStats()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.udp_bind_host, self.udp_port))
        self._sock.settimeout(0.2)
        log(f"UDP bridge listening on {self.udp_bind_host}:{self.udp_port}")

        self._thread = threading.Thread(target=self._loop, name="serial-mqtt-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _loop(self) -> None:
        assert self._sock is not None
        reassembler = SniperSerialReassembler()
        last_stats = time.monotonic()

        while not self._stop.is_set():
            try:
                datagram, _addr = self._sock.recvfrom(65535)
            except socket.timeout:
                self._maybe_log_stats(last_stats)
                if time.monotonic() - last_stats >= self.stats_interval:
                    last_stats = time.monotonic()
                continue
            except OSError:
                break

            if len(datagram) != CUSTOM_BLOCK_SIZE:
                self.stats.udp_bad_size += 1
                self._maybe_log_stats(last_stats)
                continue

            self.stats.udp_300_rx += 1
            sub_packets = build_sniper_sub_packets(datagram)
            reassembled: Optional[bytes] = None

            for sub_packet in sub_packets:
                self.stats.serial_sub_packets += 1
                try:
                    reassembled = reassembler.feed(sub_packet)
                    self.stats.crc_ok += 1
                except ValueError as exc:
                    self.stats.crc_bad += 1
                    log(str(exc))
                    reassembled = None
                    break

            if reassembled is None:
                self._maybe_log_stats(last_stats)
                continue

            self.stats.reassembled_300 += 1
            if self.publisher.publish_custom_block(reassembled):
                self.stats.mqtt_published += 1
            else:
                self.stats.mqtt_publish_failed += 1

            if self._maybe_log_stats(last_stats):
                last_stats = time.monotonic()

    def _maybe_log_stats(self, last_stats: float) -> bool:
        if time.monotonic() - last_stats < self.stats_interval:
            return False
        log(
            "stats "
            f"udp_300_rx={self.stats.udp_300_rx} "
            f"udp_bad_size={self.stats.udp_bad_size} "
            f"serial_sub_packets={self.stats.serial_sub_packets} "
            f"crc_ok={self.stats.crc_ok} "
            f"crc_bad={self.stats.crc_bad} "
            f"reassembled_300={self.stats.reassembled_300} "
            f"mqtt_published={self.stats.mqtt_published} "
            f"mqtt_publish_failed={self.stats.mqtt_publish_failed}"
        )
        return True


def start_camera_node(args: argparse.Namespace) -> ManagedProcess:
    cmd = [
        "ros2",
        "run",
        "hik_camera_ros2_driver",
        "hik_camera_ros2_driver_node",
        "--ros-args",
        "-r",
        "__node:=camera_node",
        "--params-file",
        str(args.camera_params),
        "-p",
        "enable_shm_output:=true",
        "-p",
        f"shm_name:={args.shm_name}",
    ]
    return start_managed_process("hik_camera_ros2_driver", cmd, args, quiet=args.quiet_ros)


def start_serial_driver(args: argparse.Namespace, params_file: Path) -> ManagedProcess:
    cmd = [
        "ros2",
        "run",
        "rm_serial_driver",
        "rm_serial_driver_node",
        "--ros-args",
        "--params-file",
        str(params_file),
    ]
    return start_managed_process("rm_serial_driver", cmd, args, quiet=args.quiet_ros)


def start_sender(
    args: argparse.Namespace,
    video_path: Optional[Path] = None,
    loop: Optional[bool] = None,
) -> ManagedProcess:
    cmd = [
        "ros2",
        "run",
        "doorlock_stream_e2e",
        "gst_e2e_sender",
        "--mode",
        args.source_mode,
    ]
    if args.source_mode == "file":
        cmd.extend(["--file", str(video_path or args.video)])
    elif args.source_mode == "shm":
        cmd.extend(["--shm-name", args.shm_name])
    else:
        raise ValueError(f"unsupported source mode: {args.source_mode}")

    cmd.extend([
        "--output",
        "ros2",
        "--fps",
        str(args.fps),
        "--bitrate",
        str(args.bitrate),
        "--mtu",
        str(args.mtu),
        "--loop",
        "true" if (args.loop if loop is None else loop) else "false",
        "--crop-size",
        str(args.crop_size),
        "--output-size",
        str(args.output_size),
        "--enable-display",
        "true" if args.sender_display else "false",
        "--enable-custom-block-serialization",
        "true" if args.sender_serialize_custom_block else "false",
    ])
    name = "gst_e2e_sender"
    if args.source_mode == "file":
        name = f"gst_e2e_sender:{Path(video_path or args.video).name}"
    return start_managed_process(name, cmd, args, quiet=args.quiet_sender)


def natural_sort_key(path: Path) -> list[object]:
    parts = re.split(r"(\d+)", path.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def collect_video_playlist(args: argparse.Namespace) -> list[Path]:
    if args.video_dir is None:
        return []
    videos = [
        path for path in args.video_dir.glob(args.video_pattern)
        if path.is_file()
    ]
    return sorted(videos, key=natural_sort_key)


def start_web(args: argparse.Namespace):
    import app as piny_app
    import models.consts as consts
    from service.core_service import CoreService
    from tools.app_launcher import configure_logging_modes

    configure_logging_modes(piny_app.app, start_log=True)
    piny_app._component_manager = piny_app.build_component_manager()
    piny_app.service = CoreService(
        side=consts.Sides.RED,
        robot=consts.RobotTypes.HERO,
        infantry_select=0,
        mqtt_host=args.broker_host,
        port_mqtt=args.broker_port,
        udp_bind_host=args.app_udp_host,
        port_udp=args.app_udp_port,
        test_config=consts.TestConfig(if_test=True, if_mqtt_source=True),
    )
    piny_app.service.run(blocking=False)

    def run_flask() -> None:
        piny_app.app.run(
            host=args.web_host,
            port=args.web_port,
            use_reloader=False,
            debug=False,
            threaded=True,
        )

    thread = threading.Thread(target=run_flask, name="pinyclient-web", daemon=True)
    thread.start()
    log(f"PinyClient web listening on http://{args.web_host}:{args.web_port}")
    return piny_app.service


def maybe_log_web_decode_stats(web_service, last_log: float, interval: float) -> float:
    if web_service is None or time.monotonic() - last_log < interval:
        return last_log
    try:
        stats = web_service.mqtt_source.stats
        queue_size = web_service.mqtt_source.packet_queue.qsize()
    except Exception:
        return time.monotonic()
    log(
        "web_decode "
        f"rx={stats.rx_packets} "
        f"bad={stats.bad_packets} "
        f"push={stats.pushed_packets} "
        f"frame={stats.decoded_frames} "
        f"queue={queue_size} "
        f"outer_pb_300={getattr(stats, 'mqtt_outer_pb_300', 0)} "
        f"raw_300={getattr(stats, 'mqtt_raw_300', 0)} "
        f"sender_direct_297={getattr(stats, 'sender_serialized_direct_297', 0)} "
        f"sender_nested_297={getattr(stats, 'sender_serialized_nested_297', 0)}"
    )
    return time.monotonic()


def wait_for_bridge_idle(
    bridge: Optional[PtyMqttBridge],
    idle_seconds: float = PLAYLIST_DRAIN_IDLE_SEC,
    timeout: float = PLAYLIST_DRAIN_TIMEOUT_SEC,
) -> None:
    if bridge is None:
        return

    deadline = time.monotonic() + timeout
    stats = bridge.stats
    last_counts = (
        stats.serial_rx_bytes,
        stats.reassembled_300,
        stats.mqtt_published,
        stats.rtp_packets,
    )
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        time.sleep(0.05)
        stats = bridge.stats
        counts = (
            stats.serial_rx_bytes,
            stats.reassembled_300,
            stats.mqtt_published,
            stats.rtp_packets,
        )
        if counts != last_counts:
            last_counts = counts
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= idle_seconds:
            log("playlist bridge drain complete")
            return

    log("playlist bridge drain timeout; continuing")


def reset_web_decoder(web_service) -> None:
    if web_service is None:
        return
    try:
        reset_decoder = getattr(web_service.mqtt_source, "reset_decoder", None)
        if callable(reset_decoder):
            reset_decoder()
            log("web MQTT decoder reset")
    except Exception as exc:
        log(f"warning: failed to reset web MQTT decoder: {exc}")


def run_dry_run() -> int:
    source = bytes((i & 0xFF for i in range(SNIPER_TOTAL_DATA)))
    sub_packets = build_sniper_sub_packets(source)
    reassembler = SniperSerialReassembler()
    result: Optional[bytes] = None

    for sub_packet in sub_packets:
        result = reassembler.feed(sub_packet)

    if result != source:
        print("dry_run failed: reassembled data mismatch", file=sys.stderr)
        return 1

    mqtt_payload = encode_custom_byte_block(result)
    decoded = pb.CustomByteBlock()
    decoded.ParseFromString(mqtt_payload)
    if decoded.data != source:
        print("dry_run failed: protobuf CustomByteBlock mismatch", file=sys.stderr)
        return 1

    serialized_source = build_serialized_custom_block_packet(bytes(range(12, 12 + 32)))
    serialized_sub_packets = build_sniper_sub_packets(serialized_source)
    serialized_reassembler = SniperSerialReassembler()
    serialized_result: Optional[bytes] = None
    for sub_packet in serialized_sub_packets:
        serialized_result = serialized_reassembler.feed(sub_packet)
    if serialized_result != serialized_source:
        print("dry_run failed: serialized packet reassembly mismatch", file=sys.stderr)
        return 1
    serialized_inner = extract_serialized_custom_block(serialized_result)
    if serialized_inner is None or len(serialized_inner) != CUSTOM_BLOCK_SERIALIZED_INNER_SIZE:
        print("dry_run failed: serialized CustomByteBlock extraction mismatch", file=sys.stderr)
        return 1
    if extract_fixed_packet_payload(serialized_result) != bytes(range(12, 12 + 32)):
        print("dry_run failed: serialized fixed packet decode mismatch", file=sys.stderr)
        return 1

    class _DryRunPublisher:
        def __init__(self) -> None:
            self.payloads: list[bytes] = []

        def publish_custom_block(self, payload_300: bytes) -> bool:
            self.payloads.append(payload_300)
            return True

    publisher = _DryRunPublisher()
    bridge = PtyMqttBridge(
        master_fd=-1,
        publisher=publisher,
        stats_interval=999.0,
        init_interval=999.0,
    )
    noisy_stream = (
        sub_packets[0] +
        b"\x00\x55" +
        sub_packets[1] +
        b"\x11" +
        sub_packets[2] +
        b"\x22\x33" +
        sub_packets[3] +
        sub_packets[4]
    )
    leftover = bridge._consume_buffer(noisy_stream)
    if leftover or publisher.payloads != [source]:
        print("dry_run failed: noisy serial stream was not reassembled", file=sys.stderr)
        return 1

    publisher.payloads.clear()
    leftover = bridge._consume_buffer(b"".join(serialized_sub_packets))
    if leftover or publisher.payloads != [serialized_source]:
        print("dry_run failed: serialized serial stream was not reassembled", file=sys.stderr)
        return 1

    print(
        "dry_run ok: "
        f"serial_sub_packets={len(sub_packets)} "
        f"serial_wire_bytes={sum(len(p) for p in sub_packets)} "
        f"headers={[hex(p[0]) for p in sub_packets]} "
        f"mqtt_payload_bytes={len(mqtt_payload)} "
        f"serialized_sender_payload_bytes={len(serialized_source)} "
        f"serialized_inner_bytes={len(serialized_inner)}"
    )
    return 0


def validate_args(args: argparse.Namespace) -> None:
    if args.dry_run:
        return
    if not args.hero_root.exists():
        raise FileNotFoundError(f"hero workspace not found: {args.hero_root}")
    if args.ros_distro_setup and not args.ros_distro_setup.exists():
        raise FileNotFoundError(f"ROS distro setup not found: {args.ros_distro_setup}")
    if not args.ros_setup.exists():
        raise FileNotFoundError(f"hero ROS setup not found: {args.ros_setup}")
    if args.source_mode == "shm" and not args.no_camera and not args.camera_params.exists():
        raise FileNotFoundError(f"camera params file not found: {args.camera_params}")
    if not args.no_sender:
        if args.source_mode == "file" and args.video_dir is not None:
            if not args.video_dir.exists():
                raise FileNotFoundError(f"video directory not found: {args.video_dir}")
            if not collect_video_playlist(args):
                raise FileNotFoundError(
                    f"no videos matched {args.video_pattern!r} in {args.video_dir}"
                )
        elif args.source_mode == "file" and not args.video.exists():
            raise FileNotFoundError(f"video file not found: {args.video}")
    if args.mtu != CUSTOM_BLOCK_SIZE:
        log(f"warning: sender mtu is {args.mtu}, expected 300 for this simulation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run camera/file -> gst_e2e_sender -> rm_serial_driver -> virtual serial "
            "-> MQTT -> PinyClient web."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="Run protocol self-check only.")
    parser.add_argument("--hero-root", type=Path, default=Path("/home/hpy/pioneer/hero"))
    parser.add_argument(
        "--ros-distro-setup",
        type=Path,
        default=Path("/opt/ros/humble/setup.bash"),
        help="ROS distro setup script sourced before the workspace setup.",
    )
    parser.add_argument(
        "--ros-setup",
        type=Path,
        default=Path("/home/hpy/pioneer/hero/install/setup.bash"),
        help="Workspace setup script for hik_camera_ros2_driver, doorlock_stream_e2e and rm_serial_driver.",
    )
    parser.add_argument("--video", type=Path, default=Path("/home/hpy/pioneer/hero/source/8.mp4"))
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=None,
        help="Play all matched videos in this directory one by one when source-mode=file.",
    )
    parser.add_argument("--video-pattern", default="*.mp4")
    parser.add_argument(
        "--repeat-playlist",
        action="store_true",
        help="Restart from the first video after the playlist ends.",
    )
    parser.add_argument(
        "--source-mode",
        choices=("shm", "file"),
        default="shm",
        help="gst_e2e_sender input source. shm matches the real Hik camera bringup path.",
    )
    parser.add_argument("--shm-name", default="/hik_camera_rgb")
    parser.add_argument(
        "--camera-params",
        type=Path,
        default=Path(
            "/home/hpy/pioneer/hero/src/rm_vision_hero/rm_vision/"
            "rm_vision_bringup/config/node_params.yaml"
        ),
    )
    parser.add_argument("--no-camera", action="store_true", help="Do not start hik_camera_ros2_driver.")
    parser.add_argument(
        "--camera-start-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for the shared-memory file after starting the camera node.",
    )
    parser.add_argument("--no-sender", action="store_true", help="Do not start gst_e2e_sender.")
    parser.add_argument("--quiet-sender", action="store_true", help="Hide gst_e2e_sender output.")
    parser.add_argument(
        "--sender-display",
        action="store_true",
        help="Show gst_e2e_sender OpenCV debug windows: raw, green detection, ROI and pre-send image.",
    )
    parser.add_argument(
        "--sender-serialize-custom-block",
        action="store_true",
        help=(
            "Ask gst_e2e_sender to pre-serialize the 300B payload as a CustomByteBlock. "
            "Serial remains 5x63B; MQTT bridge still publishes the outer CustomByteBlock."
        ),
    )
    parser.add_argument("--quiet-ros", action="store_true", help="Hide camera and serial-driver output.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--bitrate", type=int, default=60)
    parser.add_argument("--mtu", type=int, default=300)
    parser.add_argument("--loop", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--crop-size", type=int, default=800)
    parser.add_argument("--output-size", type=int, default=300)
    parser.add_argument("--broker-host", default="127.0.0.1")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--mqtt-topic", default=CUSTOM_BLOCK_TOPIC)
    parser.add_argument("--mqtt-client-id", default=f"local_serial_bridge_{os.getpid()}")
    parser.add_argument("--serial-baud-rate", type=int, default=115200)
    parser.add_argument("--serial-send-rate", type=float, default=58.0)
    parser.add_argument("--serial-init-interval", type=float, default=2.0)
    parser.add_argument("--no-web", action="store_true", help="Do not start PinyClient web.")
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=5000)
    parser.add_argument("--app-udp-host", default="127.0.0.1")
    parser.add_argument(
        "--app-udp-port",
        type=int,
        default=0,
        help="Unused UDP source bind port for CoreService; 0 avoids local port conflicts.",
    )
    parser.add_argument("--stats-interval", type=float, default=1.0)
    parser.add_argument(
        "--run-seconds",
        type=float,
        default=0.0,
        help="Stop automatically after N seconds; 0 means run until Ctrl+C.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        return run_dry_run()

    validate_args(args)

    stop_event = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    managed_processes: list[ManagedProcess] = []
    sender_proc: Optional[ManagedProcess] = None
    web_service = None
    master_fd: Optional[int] = None
    slave_fd: Optional[int] = None
    serial_params_file: Optional[Path] = None
    bridge: Optional[PtyMqttBridge] = None
    publisher = MqttPublisher(
        host=args.broker_host,
        port=args.broker_port,
        client_id=args.mqtt_client_id,
        topic=args.mqtt_topic,
    )
    playlist = collect_video_playlist(args) if args.source_mode == "file" else []
    playlist_index = 0

    try:
        master_fd, slave_fd = pty.openpty()
        tty.setraw(master_fd)
        tty.setraw(slave_fd)
        slave_name = os.ttyname(slave_fd)
        serial_params_file = create_serial_params_file(args, slave_name)
        log(f"virtual lower-computer serial port: {slave_name}")

        publisher.start()
        bridge = PtyMqttBridge(
            master_fd=master_fd,
            publisher=publisher,
            stats_interval=args.stats_interval,
            init_interval=args.serial_init_interval,
        )
        bridge.start()
        bridge.send_init_packet()

        if not args.no_web:
            web_service = start_web(args)

        if args.source_mode == "shm" and not args.no_camera:
            initial_shm_sequence = read_shm_sequence(args.shm_name)
            managed_processes.append(start_camera_node(args))
            if wait_for_shm(args.shm_name, args.camera_start_timeout, initial_shm_sequence):
                log(f"shared memory is available: {shm_path(args.shm_name)}")
            else:
                raise RuntimeError(
                    f"shared memory {args.shm_name} did not receive a new frame within "
                    f"{args.camera_start_timeout:.1f}s"
                )

        managed_processes.append(start_serial_driver(args, serial_params_file))
        time.sleep(1.0)
        bridge.send_init_packet()

        if not args.no_sender:
            if playlist:
                log(f"playlist contains {len(playlist)} video(s)")
                log(f"playing video 1/{len(playlist)}: {playlist[0]}")
                sender_proc = start_sender(args, video_path=playlist[0], loop=False)
            else:
                sender_proc = start_sender(args)

        log("simulation running; press Ctrl+C to stop")
        deadline = None if args.run_seconds <= 0 else time.monotonic() + args.run_seconds
        last_web_stats = 0.0
        while not stop_event.is_set():
            for managed in managed_processes:
                if managed.proc.poll() is not None:
                    log(f"{managed.name} exited with code {managed.proc.returncode}")
                    return managed.proc.returncode or 1
            if sender_proc is not None and sender_proc.proc.poll() is not None:
                sender_code = sender_proc.proc.returncode or 0
                if playlist and sender_code == 0:
                    playlist_index += 1
                    if playlist_index >= len(playlist):
                        if args.repeat_playlist:
                            playlist_index = 0
                        else:
                            log("playlist finished")
                            break
                    wait_for_bridge_idle(bridge)
                    reset_web_decoder(web_service)
                    log(
                        f"playing video {playlist_index + 1}/{len(playlist)}: "
                        f"{playlist[playlist_index]}"
                    )
                    sender_proc = start_sender(
                        args,
                        video_path=playlist[playlist_index],
                        loop=False,
                    )
                else:
                    log(f"{sender_proc.name} exited with code {sender_proc.proc.returncode}")
                    return sender_code or 1
            last_web_stats = maybe_log_web_decode_stats(
                web_service, last_web_stats, args.stats_interval
            )
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(0.2)
    finally:
        log("stopping simulation")
        if sender_proc is not None:
            sender_proc.stop()
        for managed in reversed(managed_processes):
            managed.stop()
        if bridge is not None:
            bridge.stop()
        publisher.stop()
        if web_service is not None:
            web_service.stop()
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if slave_fd is not None:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        if serial_params_file is not None:
            try:
                serial_params_file.unlink()
            except FileNotFoundError:
                pass
        stats = bridge.stats if bridge is not None else BridgeStats()
        log(
            "final stats "
            f"serial_rx_bytes={stats.serial_rx_bytes} "
            f"serial_sub_packets={stats.serial_sub_packets} "
            f"crc_ok={stats.crc_ok} "
            f"crc_bad={stats.crc_bad} "
            f"serial_bad_groups={stats.serial_bad_groups} "
            f"reassembled_300={stats.reassembled_300} "
            f"mqtt_published={stats.mqtt_published} "
            f"rtp_packets={stats.rtp_packets} "
            f"rtp_frames={stats.rtp_frames} "
            f"rtp_payload_bytes={stats.rtp_payload_bytes}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
