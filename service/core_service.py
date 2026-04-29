import sys
import time
from pprint import pprint
import threading
sys.path.append("..")  # 将上级目录添加到模块搜索路径中
from enum import Enum

from service.img_receiver import NormalImgSource, MqttImgSource
from service.mqtt_client import RMMQTTClient
import models.consts as consts
from models.message import get_message_class, TOPIC2MSG
from models.base import BaseMessage
from tools.rm_logger import RMColorLogger

logger = RMColorLogger("CoreService")

class CoreService:
    def __init__(self, side: consts.Sides, robot:consts.RobotTypes, infantry_select: int = 0, host: str = "127.0.0.1", mqtt_host: str | None = None, udp_bind_host: str | None = None, port_udp: int = 3334, port_mqtt: int = 3333,
                 subscribe_topics: set[str] = consts.DOWNLINK_TOPICS, publish_topics: set[str] = consts.UPLINK_TOPICS, test_config:consts.TestConfig = consts.TestConfig()
                 ):
        # self.host = host
        # self.port_udp = port_udp
        # self.port_mqtt = port_mqtt
        self.player_type = consts.PlayerTypes(Side=side, Robot=robot, Infantry_Select=infantry_select)
        # [架构约束]
        # MQTT 连接地址与 UDP 监听地址必须分离：
        # - mqtt_target_host: 远端 Broker 地址
        # - udp_target_host: 本机 bind 地址
        # 兼容旧参数：未显式传入时沿用 host。
        mqtt_target_host = mqtt_host or host
        udp_target_host = udp_bind_host or host
        # MQTT 客户端配置(订阅和发布，其中发布不需要传入订阅的主题与处理函数)
        self.core_mqtt = RMMQTTClient(cli_id=str(self.player_type.get_id()), host=mqtt_target_host, port=port_mqtt, subscribe_topics=subscribe_topics, handler=TOPIC2MSG, callback=self.update_state, description="core client")
        # 图传数据源配置
        self.normal_source = NormalImgSource(host=udp_target_host, port=port_udp)
        self.mqtt_source = MqttImgSource(mqtt=self.core_mqtt)  # 将MQTT客户端实例传入图传数据源，使其能够直接从MQTT消息中获取图像数据
        self._stop_event = threading.Event()
        self._mode_monitor_thread: threading.Thread = threading.Thread(target=self._mode_monitor_loop, daemon=True)
        self._source_switch_lock = threading.Lock()
        self.if_mqtt_source = False
        # self.main_method = main_method
        # self.main_method_args = main_method_args
        # self.main_method_kwargs = main_method_kwargs  # 可选的主方法，在 run() 中调用
        self.test_config = test_config

    def publish(self, topic: str, message: dict):
        if topic not in consts.UPLINK_TOPICS:
            logger.error(f"尝试发布消息到未定义的主题: {topic}")
            raise ValueError(f"主题 {topic} 不在可发布的主题列表中, 所有可发布的主题: {consts.UPLINK_TOPICS}")
        message_class = get_message_class(topic)()
        if message_class is None:
            logger.error(f"无法找到主题 {topic} 对应的消息类")
            raise ValueError(f"未知的消息主题: {topic}")
        try:
            message_obj = message_class.from_dict(message)  # 将字典转换为消息对象
            payload = message_obj.to_protobuf()  # 将消息对象转换为 Protobuf 消息
            self.core_mqtt.publish(topic, payload)
            logger.info(f"成功发布消息，主题: {topic}, 内容: {payload}")
        except Exception as e:
            logger.error(f"发布消息时发生错误，主题: {topic}, 错误: {e}")
            raise
    
    def update_state(self, data: BaseMessage):
        self.core_mqtt.update(data)  # 将消息对象转换为字典并更新状态

    def _mode_monitor_loop(self):
        """
         - 图传源策略：测试模式优先；非测试下仅英雄按状态切换，其余机型固定 UDP。
         - 核心逻辑：
           - 外层循环：持续监测状态变化，决定是否需要切换图传源。
           - 第一层if-else：区分测试模式和非测试模式
             - 测试模式：根据测试配置直接决定使用 MQTT 还是 UDP。
             - 非测试模式：首先区分英雄和非英雄，英雄根据 DeployModeStatus 进行自动切换，非英雄固定使用 UDP。
           - 第二个if：仅在检测到策略变化时执行切换逻辑，避免重复切换带来的性能损耗和潜在问题。
             - 第一层if-else：根据目标策略切换到 MQTT 或 UDP，并记录切换原因（测试模式、自动模式、非英雄默认等），便于日志分析和调试。
             - 第二层if-else：在切换图传源时保持互斥，确保 MQTT 和 UDP 数据源不会同时运行，避免资源冲突和不确定行为。
        """
        
        current_policy: str | None = None
        is_hero_robot = self.player_type.Robot == consts.RobotTypes.HERO

        while not self._stop_event.is_set():
            next_policy: str
            next_use_mqtt: bool | None

            if self.test_config.if_test:
                assert not (self.test_config.if_mqtt_source and self.test_config.if_udp_source), "测试配置错误：MQTT和UDP数据源不能同时启用"
                if self.test_config.if_mqtt_source:
                    next_policy = "test_mqtt"
                    next_use_mqtt = True
                elif self.test_config.if_udp_source:
                    next_policy = "test_udp"
                    next_use_mqtt = False
                else:
                    next_policy = "test_none"
                    next_use_mqtt = None
            else:
                if not is_hero_robot:
                    next_policy = "non_hero_udp"
                    next_use_mqtt = False
                else:
                    auto_use_mqtt = self.core_mqtt.state_manager.get("DeployModeStatusSync", "status") == 1
                    next_policy = "auto_mqtt" if auto_use_mqtt else "auto_udp"
                    next_use_mqtt = auto_use_mqtt

            if current_policy != next_policy:
                if next_policy == "test_mqtt":
                    logger.warning("测试配置：启用MQTT图传数据源")
                elif next_policy == "test_udp":
                    logger.warning("测试配置：启用UDP图传数据源")
                elif next_policy == "test_none":
                    logger.warning("测试配置：未启用任何图传数据源，生成器将无法获取视频帧")
                elif next_policy == "non_hero_udp":
                    logger.info("当前机型非英雄，固定使用UDP图传数据源")
                elif next_policy == "auto_mqtt":
                    logger.info("检测到吊射模式，启用MQTT图传数据源")
                else:
                    logger.info("未检测到吊射模式，启用UDP图传数据源")

                if next_use_mqtt is None:
                    with self._source_switch_lock:
                        self.mqtt_source.stop()
                        self.normal_source.stop()
                        self.if_mqtt_source = False
                else:
                    reason = "自动模式" if next_policy.startswith("auto_") else "测试模式"
                    if next_policy == "non_hero_udp":
                        reason = "非英雄默认UDP"
                    self._apply_source(use_mqtt=next_use_mqtt, reason=reason)

                current_policy = next_policy

            self._stop_event.wait(1.0)

    def _apply_source(self, use_mqtt: bool, reason: str = ""):
        """立即切换图传源，并保持互斥。"""
        with self._source_switch_lock:
            if use_mqtt:
                self.mqtt_source.start()
                self.normal_source.stop()
                self.if_mqtt_source = True
                logger.warning(f"图传源已切换为 MQTT{f'（{reason}）' if reason else ''}")
            else:
                self.normal_source.start()
                self.mqtt_source.stop()
                self.if_mqtt_source = False
                logger.warning(f"图传源已切换为 UDP{f'（{reason}）' if reason else ''}")

    def use_mqtt_source_for_test(self):
        """测试模式下立即切换为 MQTT 图传源。"""
        self.test_config.if_test = True
        self.test_config.if_mqtt_source = True
        self.test_config.if_udp_source = False
        self._apply_source(use_mqtt=True, reason="测试模式")

    def use_udp_source_for_test(self):
        """测试模式下立即切换为 UDP 图传源。"""
        self.test_config.if_test = True
        self.test_config.if_mqtt_source = False
        self.test_config.if_udp_source = True
        self._apply_source(use_mqtt=False, reason="测试模式")

    def disable_test_mode(self):
        """关闭测试模式：英雄按状态恢复自动策略，非英雄恢复默认 UDP。"""
        self.test_config.if_test = False
        self.test_config.if_mqtt_source = False
        self.test_config.if_udp_source = False
        if self.player_type.Robot == consts.RobotTypes.HERO:
            auto_use_mqtt = self.core_mqtt.state_manager.get("DeployModeStatusSync", "status") == 1
            self._apply_source(use_mqtt=auto_use_mqtt, reason="恢复自动模式")
        else:
            self._apply_source(use_mqtt=False, reason="非英雄默认UDP")
    
    def start(self):
        """核心启动逻辑"""
        if self._mode_monitor_thread and self._mode_monitor_thread.is_alive():
            logger.warning("CoreService 已经在运行")
            return

        self._stop_event.clear()
        self.core_mqtt.start()
        self._mode_monitor_thread = threading.Thread(target=self._mode_monitor_loop, daemon=True)
        self._mode_monitor_thread.start()

    def run(self, blocking: bool = True) -> bool:
        """启动服务，默认阻塞当前线程保持运行，直到收到退出信号。返回是否启动成功。"""
        try:
            self.start()
            if not blocking:
                logger.info("CoreService 已在后台启动（非阻塞模式）")
                return True
            # if self.main_method:
            #     logger.info("主线程方法开始执行，CoreService 将继续保持运行，等待退出信号...")
            #     # main_method（如 Flask app.run）通常是阻塞调用，返回即视为主线程方法结束。
            #     self.main_method(*self.main_method_args, **self.main_method_kwargs)
            #     logger.info("主线程方法已返回，CoreService 即将停止...")
            #     self.stop()
            #     return
            while not self._stop_event.is_set():
                time.sleep(0.5)
            return True
        except KeyboardInterrupt:
            logger.warning("收到退出信号，正在关闭 CoreService...")
            self.stop()
            return False

    def stop(self):
        self._stop_event.set()

        if self._mode_monitor_thread and self._mode_monitor_thread.is_alive():
            self._mode_monitor_thread.join(timeout=2.0)

        logger.info("停止MQTT客户端...")
        self.core_mqtt.stop()
        logger.info("停止UDP图传接收线程...")
        self.normal_source.stop()
        logger.info("停止MQTT图传接收线程...")
        self.mqtt_source.stop()
        logger.info("所有核心服务已停止")

    def get_cur_handler(self) -> NormalImgSource | MqttImgSource:
        """获取当前使用的图传数据源实例，便于外部直接调用 get_frame() 获取图像数据。"""
        if self.if_mqtt_source:
            return self.mqtt_source
        else:
            return self.normal_source
    
    def get(self, topic: str, key: str | None = None) -> dict | str | int | list | None:
        """根据主题和字段名获取当前状态值"""
        return self.core_mqtt.state_manager.get(topic, key)
    
    def get_all(self) -> dict:
        """获取所有状态数据，便于调试使用。"""
        return self.core_mqtt.state_manager.get_all()
    
    # 测试辅助方法

    def print_all_topics(self):
        pprint(self.get_all())
    
    def print_topic(self, topic: str):
        pprint(self.get(topic))
    
    def print_topic_key(self, topic: str, key: str):
        print(self.get(topic, key))

    def print_if_alive(self):
        """检查核心服务的基本运行状态，便于外部调用时快速判断服务是否正常工作。"""
        mqtt_alive: bool = self.core_mqtt.client.is_connected()
        try:
            _ = self.normal_source.sock.getsockname() # pyright: ignore[reportOptionalMemberAccess]
            udp_alive = True
        except Exception:
            udp_alive = False
        udp_source_alive: bool = bool(self.normal_source.decode_thread.is_alive()) if self.normal_source.decode_thread else False
        mqtt_source_alive: bool = bool(self.mqtt_source.decode_thread.is_alive()) if self.mqtt_source.decode_thread else False
        dynamic_switch_alive: bool = bool(self._mode_monitor_thread.is_alive()) if self._mode_monitor_thread else False
        print(f"MQTT 连接状态: {mqtt_alive}\nUDP socket状态: {udp_alive}\nMQTT 链路解码线程状态: {mqtt_source_alive}\nUDP 链路解码线程状态: {udp_source_alive}\n当前图传数据源: {'MQTT' if self.if_mqtt_source else 'UDP'}\n图传源服务动态切换线程状态:{dynamic_switch_alive}")

    def print_current_source(self):
        """打印当前使用的图传数据源，便于外部调用时快速判断当前模式。"""
        print(f"当前图传数据源: {'MQTT' if self.if_mqtt_source else 'UDP'}")

if __name__ == "__main__":
    service = CoreService(side=consts.Sides.RED, robot=consts.RobotTypes.INFANTRY, infantry_select=2)
    # 便于 `python -i` 进入交互后直接使用 service 实例。
    globals()["service"] = service
    # def send_demo_publish_messages(service: "CoreService"):
    #     """发送一组用于联调的示例消息。"""
    #     test_cases: list[tuple[str, dict]] = [
    #         (
    #             "AssemblyCommand",
    #             {
    #                 "operation": 1,
    #                 "difficulty": 2,
    #             },
    #         ),
    #         (
    #             "CommonCommand",
    #             {
    #                 "cmd_type": 3,
    #                 "param": 0,
    #             },
    #         ),
    #         (
    #             "MapClickInfoNotify",
    #             {
    #                 "is_send_all": 0,
    #                 "robot_id": "AQIAAAAAAA==",  # 7字节示例(1,2,0,0,0,0,0)的Base64
    #                 "mode": 1,
    #                 "enemy_id": 101,
    #                 "ascii": 33,
    #                 "type": 1,
    #                 "screen_x": 640,
    #                 "screen_y": 360,
    #                 "map_x": 12.5,
    #                 "map_y": 6.25,
    #             },
    #         ),
    #         (
    #             "CustomControl",
    #             {
    #                 "data": "MTExMTE=",  # b"11111" 的 Base64
    #             },
    #         ),
    #     ]

    #     for topic, payload in test_cases:
    #         try:
    #             service.publish(topic, payload)
    #             logger.info(f"测试发布完成，topic={topic}")
    #         except Exception as exc:
    #             logger.error(f"测试发布失败，topic={topic}, error={exc}")
    # 在 `python -i` 交互模式下默认非阻塞启动，避免看起来“卡住”。
    interactive_mode = bool(getattr(sys.flags, "interactive", 0))
    service.run(blocking=not interactive_mode)
    stat = service.get("DeployModeStatusSync", "status")  # 触发一次状态获取，验证 MQTT 连接和状态管理是否正常工作。
    print(f"当前 DeployModeStatusSync.status: {stat}")
    # 服务启动后发送一组示例消息，便于快速验证 publish 流程。
    # time.sleep(0.2)
    # send_demo_publish_messages(service)