from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, cast

import paho.mqtt.client as mqtt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from protocol import messages_pb2 as _messages_pb2  # noqa: E402

messages_pb2 = cast(Any, _messages_pb2)


SHOOTER_OPTION_TO_ENUM = {
    "冷却优先": 1,
    "爆发优先": 2,
    "英雄近战优先": 3,
    "英雄远程优先": 4,
}

CHASSIS_OPTION_TO_ENUM = {
    "血量优先": 1,
    "功率优先": 2,
    "英雄近战优先": 3,
    "英雄远程优先": 4,
}

DART_TARGET_TO_ID = {
    "前哨": 1,
    "基地固定": 2,
    "基地随机固定": 3,
    "基地随机移动": 4,
    "基地末端移动": 5,
}

DART_ID_TO_TARGET = {v: k for k, v in DART_TARGET_TO_ID.items()}
SHOOTER_ENUM_TO_OPTION = {v: k for k, v in SHOOTER_OPTION_TO_ENUM.items()}
CHASSIS_ENUM_TO_OPTION = {v: k for k, v in CHASSIS_OPTION_TO_ENUM.items()}


class ProtocolBridge:
    debug: bool = False  # 设为 True 可在控制台打印每条收到的协议消息

    def __init__(self, host: str = "127.0.0.1", port: int = 3333, client_id: str = "reflex-cil-ui"):
        self.host = host
        self.port = port
        self.client_id = client_id
        # Prefer callback API v2 on newer paho; fall back for older versions.
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        except Exception:
            self.client = mqtt.Client(client_id=self.client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._lock = threading.Lock()
        self._connected = False
        self._cache: dict[str, Any] = {}
        self._latest_snapshot: dict[str, Any] = {}

        self._base_health_max = 5000
        self._outpost_health_max = 3000
        self._enemy_base_health_max = 5000
        self._enemy_outpost_health_max = 3000

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> str:
        try:
            self.client.connect(self.host, self.port, keepalive=30)
            self.client.loop_start()
            return f"尝试连接 MQTT {self.host}:{self.port}"
        except Exception as exc:
            self._connected = False
            return f"连接失败: {exc}"

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = True
        for topic in [
            "GameStatus",
            "GlobalUnitStatus",
            "GlobalLogisticsStatus",
            "DeployModeStatusSync",
            "DartSelectTargetStatusSync",
            "RobotRespawnStatus",
            "RobotDynamicStatus",
            "RobotStaticStatus",
        ]:
            self.client.subscribe(topic, qos=1)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False

    def _normalize_percent(self, value: int, max_value: int) -> int:
        if max_value <= 0:
            return 0
        if value <= 0:
            return 0
        result = int(round((value * 100.0) / max_value))
        return max(0, min(100, result))

    def _topic_name(self, topic: str) -> str:
        return topic.split("/")[-1]

    def _on_message(self, client, userdata, msg):
        name = self._topic_name(msg.topic)
        update: dict[str, Any] = {}

        try:
            if name == "GameStatus":
                pb = messages_pb2.GameStatus()
                pb.ParseFromString(msg.payload)
                remaining = max(0, int(pb.stage_countdown_sec))
                elapsed = max(0, int(pb.stage_elapsed_sec))
                update["remaining_time"] = remaining
                update["total_time"] = max(remaining + elapsed, 1)

            elif name == "GlobalLogisticsStatus":
                pb = messages_pb2.GlobalLogisticsStatus()
                pb.ParseFromString(msg.payload)
                update["economy_now"] = int(pb.remaining_economy)
                previous_total = int(self._latest_snapshot.get("economy_total", 0))
                update["economy_total"] = max(previous_total, int(pb.total_economy_obtained))
                update["tech_level"] = int(pb.tech_level)

            elif name == "GlobalUnitStatus":
                pb = messages_pb2.GlobalUnitStatus()
                pb.ParseFromString(msg.payload)
                base_health = int(pb.base_health)
                outpost_health = int(pb.outpost_health)
                enemy_base_health = int(pb.enemy_base_health)
                enemy_outpost_health = int(pb.enemy_outpost_health)

                self._base_health_max = max(self._base_health_max, base_health)
                self._outpost_health_max = max(self._outpost_health_max, outpost_health)
                self._enemy_base_health_max = max(self._enemy_base_health_max, enemy_base_health)
                self._enemy_outpost_health_max = max(self._enemy_outpost_health_max, enemy_outpost_health)

                update["our_base_hp"] = self._normalize_percent(base_health, self._base_health_max)
                update["our_outpost_hp"] = self._normalize_percent(outpost_health, self._outpost_health_max)
                update["enemy_base_hp"] = self._normalize_percent(enemy_base_health, self._enemy_base_health_max)
                update["enemy_outpost_hp"] = self._normalize_percent(enemy_outpost_health, self._enemy_outpost_health_max)
                update["our_damage"] = int(pb.total_damage_ally)
                update["enemy_damage"] = int(pb.total_damage_enemy)

            elif name == "DeployModeStatusSync":
                pb = messages_pb2.DeployModeStatusSync()
                pb.ParseFromString(msg.payload)
                update["deploy_enabled"] = bool(pb.status == 1)

            elif name == "DartSelectTargetStatusSync":
                pb = messages_pb2.DartSelectTargetStatusSync()
                pb.ParseFromString(msg.payload)
                update["dart_target"] = DART_ID_TO_TARGET.get(int(pb.target_id), "")
                update["dart_open_status"] = int(pb.open)

            elif name == "RobotRespawnStatus":
                pb = messages_pb2.RobotRespawnStatus()
                pb.ParseFromString(msg.payload)
                update["can_respawn"] = bool(pb.can_free_respawn)
                update["can_pay_for_respawn"] = bool(pb.can_pay_for_respawn)
                update["gold_respawn_cost"] = int(pb.gold_cost_for_respawn)

            elif name == "RobotDynamicStatus":
                pb = messages_pb2.RobotDynamicStatus()
                pb.ParseFromString(msg.payload)
                update["can_remote_heal"] = bool(pb.can_remote_heal)
                update["can_remote_ammo"] = bool(pb.can_remote_ammo)
                update["current_exp"] = int(pb.current_experience)
                update["upgrade_exp"] = int(pb.experience_for_upgrade)

            elif name == "RobotStaticStatus":
                pb = messages_pb2.RobotStaticStatus()
                pb.ParseFromString(msg.payload)
                launcher_option = SHOOTER_ENUM_TO_OPTION.get(int(pb.performance_system_shooter), "")
                chassis_option = CHASSIS_ENUM_TO_OPTION.get(int(pb.performance_system_chassis), "")
                if launcher_option:
                    update["launcher_option"] = launcher_option
                if chassis_option:
                    update["chassis_option"] = chassis_option
                update["robot_level"] = int(pb.level)

        except Exception:
            return

        if update:
            if self.debug:
                import json as _json
                print(f"[MQTT←] {name}: {_json.dumps(update, default=str)}")
            with self._lock:
                self._cache.update(update)
                self._latest_snapshot.update(update)

    def poll(self) -> dict[str, Any]:
        with self._lock:
            if not self._latest_snapshot:
                return {}
            snapshot = dict(self._latest_snapshot)
            self._cache.clear()
            return snapshot

    def _publish(self, topic: str, pb_message) -> None:
        if not self._connected:
            return
        payload = pb_message.SerializeToString()
        self.client.publish(topic, payload, qos=1)

    def send_common_command(self, cmd_type: int, param: int) -> None:
        pb = messages_pb2.CommonCommand()
        pb.cmd_type = int(cmd_type)
        pb.param = int(param)
        self._publish("CommonCommand", pb)

    def send_robot_performance_selection(self, shooter: int, chassis: int, sentry_control: int) -> None:
        pb = messages_pb2.RobotPerformanceSelectionCommand()
        pb.shooter = int(shooter)
        pb.chassis = int(chassis)
        pb.sentry_control = int(sentry_control)
        self._publish("RobotPerformanceSelectionCommand", pb)

    def send_hero_deploy_mode(self, enabled: bool) -> None:
        pb = messages_pb2.HeroDeployModeEventCommand()
        pb.mode = 1 if enabled else 0
        self._publish("HeroDeployModeEventCommand", pb)

    def send_rune_activate(self) -> None:
        pb = messages_pb2.RuneActivateCommand()
        pb.activate = 1
        self._publish("RuneActivateCommand", pb)

    def send_dart_command(self, target_id: int, open_gate: bool, launch_confirm: bool) -> None:
        pb = messages_pb2.DartCommand()
        pb.target_id = int(target_id)
        pb.open = bool(open_gate)
        pb.launch_confirm = bool(launch_confirm)
        self._publish("DartCommand", pb)


bridge = ProtocolBridge()
