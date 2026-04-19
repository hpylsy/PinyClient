import sys
import threading
import time
from typing import Dict, Any, Optional, Callable
sys.path.append("..")  # 添加项目根目录到sys.path，方便导入模块

import paho.mqtt.client as mqtt
from google.protobuf.message import DecodeError
from tools.rm_logger import RMColorLogger
from models.base import BaseMessage

logger = RMColorLogger("MQTTClient")

class MQTTStateManager:
    """线程安全的 MQTT 主题状态管理器"""
    
    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()  # 可重入锁，支持嵌套访问
        
    def update(self, topic: str, properties: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> None:
        """更新主题状态。

        规则：
        1) 若 properties 为空，则将该 topic 重置为 defaults（若提供）。
        2) 若 properties 非空，则先以 defaults 回填所有字段，再覆盖本次收到的字段。
        """
        with self._lock:
            if topic not in self._states:
                self._states[topic] = {}

            if defaults is None:
                defaults = {}

            if not properties:
                self._states[topic] = defaults.copy()
            else:
                # 先按默认值构造完整状态，再覆盖本次有值的字段。
                merged = defaults.copy()
                merged.update(properties)
                self._states[topic] = merged
            
            # 记录更新时间
            self._states[topic]['_last_update'] = time.time()
    
    def get(self, topic: str, key: Optional[str] = None) -> Any:
        """获取主题的状态或特定属性"""
        with self._lock:
            state = self._states.get(topic, {})
            if key is None:
                return state.copy()  # 返回副本，避免外部修改
            return state.get(key)
    
    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """获取所有主题的状态快照"""
        with self._lock:
            return {topic: state.copy() for topic, state in self._states.items()}
    
    # def get_topics_by_condition(self, key: str, value: Any) -> list:
    #     """根据属性值查找主题"""
    #     with self._lock:
    #         return [
    #             topic for topic, state in self._states.items()
    #             if state.get(key) == value
    #         ]


class RMMQTTClient:
    def __init__(self, cli_id, host, port, subscribe_topics=None, handler=None, callback = None, description="default") -> None:
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=cli_id)
        
        self.host = host
        self.port = port
        self.subscribe_topics = subscribe_topics or []
        self.callback = callback
        self.description = description

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_publish = self._on_publish
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect

        self.handler = handler or {}  # 消息处理函数字典，key为主题，value为处理函数
        self.raw_topic_callbacks: Dict[str, list[Callable[[bytes], None]]] = {}

        self._connected = False
        self._loop_started = False
        self._state_lock = threading.RLock()

        self.state_manager = MQTTStateManager()  # 内部状态管理器实例；任务：接收与更新进程独立
        
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            with self._state_lock:
                self._connected = True
            logger.info(f"MQTT: {self.description} 连接成功")
            # 订阅服务
            for topic in self.subscribe_topics:
                self.client.subscribe(topic)
                logger.debug(f"MQTT: {self.description} 已订阅主题: {topic}")

        else:
            logger.error(f"MQTT: {self.description} 连接失败，错误代码: {rc}")

    def _on_message(self, client, userdata, msg):
        raw_callbacks = self.raw_topic_callbacks.get(msg.topic, [])
        for cb in raw_callbacks:
            try:
                cb(msg.payload)
            except Exception as e:
                logger.error(f"MQTT: {self.description} 原始回调异常，主题: {msg.topic}, 错误: {e}")

        if msg.topic in self.handler:
            try:
                parser_cls = self.handler[msg.topic]
                parsed_msg = parser_cls()
                try:
                    parsed_msg.from_protobuf(msg.payload)
                except DecodeError:
                    # mock_gateway directly publishes raw 300-byte payload for CustomByteBlock
                    # instead of protobuf-serialized bytes; keep a compatibility fallback.
                    if msg.topic == "CustomByteBlock" and hasattr(parsed_msg, "data"):
                        parsed_msg.data = msg.payload
                        logger.debug(
                            "MQTT: %s 收到原始 CustomByteBlock 载荷，已按 bytes 兼容解析",
                            self.description,
                        )
                    else:
                        raise 
                if self.callback:
                    self.callback(parsed_msg)
            except Exception as e:
                import traceback
                traceback_str = traceback.format_exc()
                logger.error(f"MQTT: {self.description} 处理消息时发生错误，主题: {msg.topic}, 错误: {e}")
                logger.error(f"详细错误信息:\n{traceback_str}")
        else:
            logger.warning(f"MQTT: {self.description} 收到未处理的消息，主题: {msg.topic}")

    def add_raw_topic_callback(self, topic: str, callback: Callable[[bytes], None]) -> None:
        with self._state_lock:
            if topic not in self.raw_topic_callbacks:
                self.raw_topic_callbacks[topic] = []
            self.raw_topic_callbacks[topic].append(callback)

    def remove_raw_topic_callback(self, topic: str, callback: Callable[[bytes], None]) -> None:
        with self._state_lock:
            callbacks = self.raw_topic_callbacks.get(topic, [])
            if callback in callbacks:
                callbacks.remove(callback)
            if not callbacks and topic in self.raw_topic_callbacks:
                del self.raw_topic_callbacks[topic]

    def _on_disconnect(self, client, userdata, rc):
        with self._state_lock:
            self._connected = False
        logger.warning(f"MQTT: {self.description} 连接断开，返回码: {rc}")

    def _on_publish(self, client, userdata, mid):
        logger.debug(f"MQTT: {self.description} 消息发布成功，消息ID: {mid}")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        logger.debug(f"MQTT: {self.description} 订阅成功，消息ID: {mid}, QoS: {granted_qos}")

    def connect(self):
        with self._state_lock:
            if self._connected:
                logger.debug("MQTT已连接，跳过重复连接")
                return
        logger.info(f"MQTT: {self.description} 正在连接MQTT服务器 {self.host}:{self.port}...")
        while True:
            try:
                self.client.connect(self.host, self.port)
                break
            except Exception as e:
                logger.error(f"MQTT: {self.description} 连接失败: {e}, 5秒后重试...")
                time.sleep(5)  # 等待5秒后重试
        # 对于不启用网络循环回调的发布端，connect 返回即可视为连接建立。
        with self._state_lock:
            self._connected = True

    # def start_listening(self):
    #     logger.info(f"MQTT: {self.description} 正在启动接收循环...")
    #     self.client.loop_forever()

    def publish(self, topic, payload):
        self.client.publish(topic, payload)
    
    def start(self):
        self.connect()
        with self._state_lock:
            if self._loop_started:
                logger.debug("MQTT循环已启动，跳过重复启动")
                return
            self._loop_started = True        
        self.client.loop_start()

    def stop(self):
        need_loop_stop = False
        need_disconnect = False
        with self._state_lock:
            if self._loop_started:
                need_loop_stop = True
                self._loop_started = False
            if self._connected:
                need_disconnect = True
                self._connected = False

        # 避免在持锁状态下调用网络 API，防止与回调拿锁发生等待。
        if need_disconnect:
            logger.info("正在断开MQTT连接...")
            self.client.disconnect()
        if need_loop_stop:
            logger.info("正在停止MQTT网络循环...")
            self.client.loop_stop()
    
    def update(self, data: BaseMessage):
        defaults: Dict[str, Any] = {}
        pb = data._ensure_pb()
        if pb is not None:
            for field in pb.DESCRIPTOR.fields:
                # 兼容 upb / cpp 实现，优先使用 is_repeated。
                if getattr(field, "is_repeated", False):
                    defaults[field.name] = []
                else:
                    defaults[field.name] = field.default_value

        with self._state_lock:
            self.state_manager.update(data.topic(), data.to_dict(), defaults=defaults)  # 将消息对象转换为字典并更新状态

    def get(self, topic: str, key: Optional[str] = None) -> Any:
        with self._state_lock:
            return self.state_manager.get(topic, key)

if __name__ == "__main__":
    def test_message_handler(payload):
        logger.info(f"处理测试消息，内容: {payload}")
    mqtt_client = RMMQTTClient(cli_id="sentry", host="127.0.0.1", port=3333, subscribe_topics=["GameStatus"], handler={"GameStatus": test_message_handler})
    mqtt_client.connect()
    import sys
    sys.path.append("..")  # 添加项目根目录到sys.path，方便导入模块
    # 测试发布消息
    from models.message import AssemblyCommand, AssemblyOperation
    cmd = AssemblyCommand(operation=AssemblyOperation.CONFIRM, difficulty=2)
    mqtt_client.publish("AssemblyCommand", cmd.to_protobuf())
    # 测试接收消息
    mqtt_client.start()