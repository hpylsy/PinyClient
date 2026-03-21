"""
RoboMaster MQTT 客户端模块
负责与裁判系统服务器建立 MQTT 连接, 接收并解析下行数据。
状态机逻辑已分离到 states.py, 保持解耦。
"""
from __future__ import annotations

import logging
import os
import time
import random
import threading
import queue
from typing import Callable, Dict, Any

import paho.mqtt.client as mqtt
from google.protobuf.json_format import MessageToDict

from states import (
    RMClientStates, RED, BLUE, ALLY, ALL_STATES,
    CLIENT_ID_TO_NAME, NAME_TO_ID, NAME_TO_CLIENT_ID
)
from backend.protobuf_models import DOWN_TOPIC2MODEL_MAP, UPLINK_TOPIC2MODEL_MAP


# ============================================================
# 彩色日志配置 (增强版)
# ============================================================
class ColorLogger:
    """彩色日志生成器, 支持分组配色方案"""

    # 基础色
    C: dict[str, str]= {
        "RESET":   "\033[0m",
        "BOLD":    "\033[1m",
        "DIM":     "\033[2m",
        "ITALIC":  "\033[3m",
        "UNDER":   "\033[4m",

        # 前景色
        "BLACK":   "\033[30m",
        "RED":     "\033[31m",
        "GREEN":   "\033[32m",
        "YELLOW":  "\033[33m",
        "BLUE":    "\033[34m",
        "MAGENTA": "\033[35m",
        "CYAN":    "\033[36m",
        "WHITE":   "\033[37m",

        # 亮色
        "BRIGHT_RED":     "\033[91m",
        "BRIGHT_GREEN":   "\033[92m",
        "BRIGHT_YELLOW":  "\033[93m",
        "BRIGHT_BLUE":    "\033[94m",
        "BRIGHT_MAGENTA": "\033[95m",
        "BRIGHT_CYAN":    "\033[96m",
        "GRAY":           "\033[90m",

        # 背景色
        "BG_RED":     "\033[41m",
        "BG_GREEN":   "\033[42m",
        "BG_YELLOW":  "\033[43m",
        "BG_BLUE":    "\033[44m",
        "BG_MAGENTA": "\033[45m",
        "BG_CYAN":    "\033[46m",
    }

    # 分组配色方案
    THEMES: dict[str, dict[str, str]]= {
        # DEBUG 组：柔和灰蓝
        "DEBUG": {
            "time":  f"{C['GRAY']}{C['DIM']}",
            "level": f"{C['GRAY']}",
            "name":  f"{C['GRAY']}{C['ITALIC']}",
            "msg":   f"{C['GRAY']}",
        },
        # INFO 组：清新蓝绿
        "INFO": {
            "time":  f"{C['CYAN']}{C['BOLD']}",
            "level": f"{C['BRIGHT_BLUE']}{C['BOLD']}",
            "name":  f"{C['BRIGHT_CYAN']}",
            "msg":   f"{C['WHITE']}",
        },
        # WARNING 组：活力黄橙
        "WARNING": {
            "time":  f"{C['YELLOW']}{C['BOLD']}",
            "level": f"{C['BRIGHT_YELLOW']}{C['BOLD']}",
            "name":  f"{C['YELLOW']}",
            "msg":   f"{C['YELLOW']}",
        },
        # ERROR 组：醒目红紫
        "ERROR": {
            "time":  f"{C['RED']}{C['BOLD']}",
            "level": f"{C['BRIGHT_RED']}{C['BOLD']}{C['UNDER']}",
            "name":  f"{C['MAGENTA']}",
            "msg":   f"{C['BRIGHT_RED']}",
        },
        # CRITICAL 组：最强红白
        "CRITICAL": {
            "time":  f"{C['RED']}{C['BOLD']}",
            "level": f"{C['BG_RED']}{C['WHITE']}{C['BOLD']}",
            "name":  f"{C['BRIGHT_RED']}{C['BOLD']}",
            "msg":   f"{C['WHITE']}{C['BOLD']}",
        },
    }

    def __init__(self, name: str = "pioneer"):
        self.name = name
        self._logger = logging.getLogger(name)
        self._configure()

    def _configure(self):
        level_str = os.environ.get("PIONEER_LOG_LEVEL", "INFO").upper()
        self._logger.setLevel(getattr(logging, level_str, logging.INFO))
        self._logger.handlers.clear()

        class MultiColorFormatter(logging.Formatter):
            def format(self, record):
                # 先手动设置 asctime 属性
                if not hasattr(record, 'asctime'):
                    # 创建时间字符串
                    record.asctime = self.formatTime(record, self.datefmt)
                
                theme = ColorLogger.THEMES.get(record.levelname, ColorLogger.THEMES["INFO"])
                C = ColorLogger.C

                # 时间：彩色
                asctime = f"{theme['time']}{record.asctime}{C['RESET']}"
                # 级别：彩色 + 加粗
                levelname = f"{theme['level']}{record.levelname:10s}{C['RESET']}"
                # 模块名：彩色
                name = f"{theme['name']}{record.name}{C['RESET']}"
                # 消息：彩色
                message = f"{theme['msg']}{record.getMessage()}{C['RESET']}"

                # 重新组装
                return f"{asctime} | {levelname} | {name} | {message}"

        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        # 格式：[时间] | 级别 | 模块名 | 消息
        fmt = "%(asctime)s | %(levelname)-10s | %(name)s | %(message)s"
        handler.setFormatter(MultiColorFormatter(fmt, datefmt="%H:%M:%S"))
        self._logger.addHandler(handler)

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(msg, *args, **kwargs)

# 全局日志实例
logger = ColorLogger("pioneer")


# ============================================================
# 常量 (已迁移到 states.py, 此处保留向下兼容)
# ============================================================
# NAME_TO_ID, CLIENT_ID_TO_NAME, NAME_TO_CLIENT_ID, ID_TO_NAME
# 请使用: from states import NAME_TO_ID, CLIENT_ID_TO_NAME, NAME_TO_CLIENT_ID, ID_TO_NAME

ALLOWED_CLIENT_ID: list[int] = list(CLIENT_ID_TO_NAME.keys())

DOWNLINK_TOPICS = {
    "GameStatus", "GlobalUnitStatus", "GlobalLogisticsStatus",
    "GlobalSpecialMechanism", "Event", "RobotInjuryStat",
    "RobotRespawnStatus", "RobotStaticStatus", "RobotDynamicStatus",
    "RobotModuleStatus", "RobotPosition", "Buff", "PenaltyInfo",
    "RobotPathPlanInfo", "RadarInfoToClient", "CustomByteBlock",
    "TechCoreMotionStateSync", "RobotPerformanceSelectionSync",
    "DeployModeStatusSync", "RuneStatusSync", "SentryStatusSync",
    "DartSelectTargetStatusSync", "SentryCtrlResult", "AirSupportStatusSync",
}

UPLINK_TOPICS = {
    "CommonCommand", "RobotPerformanceSelectionCommand",
    "HeroDeployModeEventCommand", "RuneActivateCommand", "DartCommand",
    "MapSentryPathSearchCommand", "SentryPathControlCommand",
    "MapRadarMarkCommand", "AirsupportCommand",
    "TechCoreAssembleOperationCommand",
}


# ============================================================
# 主类
# ============================================================
class RoboMasterMQTT:
    """
    MQTT 客户端, 连接裁判系统服务器, 接收比赛数据并更新状态机。
    """

    # 每个 topic 对应状态机中哪些字段需要更新
    # ALL_STATES = 全量更新；列表 = 选择性更新
    UPDATE_ITEMS: Dict[str, Any] = {
        "GameStatus": ["red_score", "blue_score", "stage_countdown_sec", "stage_elapsed_sec"],
        **{topic: ALL_STATES for topic in DOWNLINK_TOPICS if topic != "GameStatus"},
    }

    def __init__(self, client_id: int, host: str = "192.168.12.1", port: int = 3333):
        if client_id not in CLIENT_ID_TO_NAME:
            logger.critical("无效的 client_id: %s, 允许值: %s", client_id, list(CLIENT_ID_TO_NAME.keys()))
            raise ValueError(f"Invalid client_id: {client_id}")

        self.client_id = client_id
        self.host = host
        self.port = port

        # 通过 CLIENT_ID 判断阵营颜色 (0x01xx = 红方, 0x0165~ = 蓝方)
        robot_name = CLIENT_ID_TO_NAME.get(client_id, "")
        ally_color = RED if robot_name.startswith("RED") else BLUE
        
        # 状态机（独立类, 可单独提取给 HTTP 模块使用）
        self.states = RMClientStates(ally_color=ally_color)

        # MQTT 客户端
        self._mqtt = mqtt.Client(client_id=str(client_id))
        self._mqtt.on_connect    = self._on_connect
        self._mqtt.on_message   = self._on_message
        self._mqtt.on_disconnect = self._on_disconnect

        # 消息队列（有界, 满了丢弃最旧消息）
        self._queue: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=500)

        # 回调表
        self._callbacks: Dict[str, Callable[[bytes], None]] = {}

        # 发布锁
        self._publish_lock = threading.Lock()

        logger.info(
            "MQTT[%s: %s] 初始化完成, 连接目标 %s:%s",
            CLIENT_ID_TO_NAME.get(client_id, client_id), hex(client_id), host, port
        )

    # --------------------------------------------------------
    # MQTT 生命周期
    # --------------------------------------------------------
    def start(self) -> None:
        """启动 MQTT 客户端（连接 + 消息处理线程）。"""
        self._register_callbacks()
        self._connect_loop()
        threading.Thread(target=self._process_messages, name="msg_processor", daemon=True).start()
        logger.info("MQTT 客户端已启动")

    def stop(self) -> None:
        """断开连接并停止线程。"""
        self._mqtt.loop_stop()
        self._mqtt.disconnect()
        logger.info("MQTT 客户端已停止")

    def _connect_loop(self) -> None:
        """指数退避重连。"""
        max_delay = 30
        delay = 1.0
        attempt = 0
        while True:
            try:
                self._mqtt.connect(self.host, self.port, keepalive=60)
                self._mqtt.loop_start()
                logger.info("已连接到 %s:%s", self.host, self.port)
                return
            except Exception as e:
                attempt += 1
                logger.warning("第 %d 次连接失败: %s, %.1fs 后重试...", attempt, e, delay)
                time.sleep(delay)
                delay = min(delay * 1.5 + random.uniform(0, 0.5), max_delay)

    def _on_connect(self, _client, _userdata, flags, rc: int) -> None:
        if rc == 0:
            logger.info("连接成功, 已订阅 %d 个 topic", len(DOWNLINK_TOPICS))
            for topic in DOWNLINK_TOPICS:
                self._mqtt.subscribe(topic)
        else:
            logger.error("连接失败, rc=%d", rc)

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            self._queue.put_nowait((msg.topic, msg.payload))
        except queue.Full:
            # 丢弃队列最旧消息，为新消息腾出空间
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((msg.topic, msg.payload))
                logger.warning("消息队列已满，丢弃最旧消息，topic=%s", msg.topic)
            except queue.Empty:
                logger.warning("消息队列已满，丢弃当前消息，topic=%s", msg.topic)

    def _on_disconnect(self, _client, _userdata, rc: int) -> None:
        logger.warning("连接断开 (rc=%d), 正在重连...", rc)
        self._connect_loop()

    # --------------------------------------------------------
    # 消息处理
    # --------------------------------------------------------
    def _process_messages(self) -> None:
        """消息处理循环：从队列取消息 → 解析 → 更新状态机。"""
        logger.info("消息处理线程已启动")
        while True:
            topic, payload = self._queue.get()
            if topic in self._callbacks:
                try:
                    self._callbacks[topic](payload)
                except Exception as e:
                    logger.error("处理 %s 时出错: %s", topic, e)

    def _register_callbacks(self) -> None:
        """
        批量注册所有 topic 的回调。
        """
        def parse_and_update(topic: str, payload: bytes) -> None:
            """解析 Protobuf 消息并更新状态机。"""
            model_cls = DOWN_TOPIC2MODEL_MAP.get(topic)
            if model_cls is None:
                logger.warning("未找到 topic '%s' 的 Protobuf 模型, 跳过", topic)
                return

            msg = model_cls()
            try:
                msg.ParseFromString(payload)
            except Exception as e:
                logger.error("解析 %s 失败: %s", topic, e)
                return

            # 按配置更新状态机
            update_spec = self.UPDATE_ITEMS.get(topic, ALL_STATES)
            
            if update_spec == ALL_STATES:
                # 全量更新：转为嵌套字典 {topic: {...}}
                msg_dict = MessageToDict(msg, preserving_proto_field_name=True)
                self.states.update({topic: msg_dict})
                logger.debug("[%s] 全量更新", topic)
            elif isinstance(update_spec, list):
                # 选择性更新：只提取指定字段
                nested = {}
                for field in update_spec:
                    val = getattr(msg, field, None)
                    if val is not None:
                        nested[field] = val
                self.states.update({topic: nested})
                logger.debug("[%s] 选择更新: %s", topic, list(nested.keys()))

        for topic in DOWNLINK_TOPICS:
            self._callbacks[topic] = lambda payload, t=topic: parse_and_update(t, payload)
        logger.debug("已注册 %d 个 topic 回调", len(self._callbacks))

    # --------------------------------------------------------
    # 状态查询（委托给状态机）
    # --------------------------------------------------------
    def state_update(self, state, msgs: Any = None) -> None:
        """兼容旧 API, 内部转发给状态机。"""
        if state == ALL_STATES and msgs is not None:
            # 尝试推断 topic 名称
            topic = type(msgs).__name__
            msg_dict = MessageToDict(msgs, preserving_proto_field_name=True)
            self.states.update({topic: msg_dict})

    # --------------------------------------------------------
    # 发送指令
    # --------------------------------------------------------
    def publish(self, topic: str, message: bytes) -> None:
        """发送上行指令到裁判系统服务器。"""
        with self._publish_lock:
            result = self._mqtt.publish(topic, message)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error("发布 %s 失败, rc=%d", topic, result.rc)
            else:
                logger.debug("已发布 %s", topic)

    def publish_command(self, topic: str, msg) -> None:
        """序列化 Protobuf 消息并发送（便捷封装）。"""
        if topic not in UPLINK_TOPIC2MODEL_MAP:
            logger.warning("未知上行 topic: %s", topic)
            return
        data = msg.SerializeToString()
        self.publish(topic, data)


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    # 使用十六进制 CLIENT_ID (0x0101 = 红方英雄)
    r = RoboMasterMQTT(client_id=NAME_TO_CLIENT_ID["RED_HERO"], host="localhost", port=3333)
    r.start()
