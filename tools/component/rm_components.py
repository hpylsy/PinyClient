from typing import Any

try:
    from .rm_component_base import Component, GridConfig, BlockPosition
except ImportError:
    from rm_component_base import Component, GridConfig, BlockPosition


MISSING_VALUE = "--"


GAME_STAGE_LABELS = {
    0: "未开始",
    1: "准备阶段",
    2: "自检阶段",
    3: "五秒倒计时",
    4: "比赛中",
    5: "结算阶段",
    "NOT_STARTED": "未开始",
    "PREPARATION": "准备阶段",
    "SELF_CHECK": "自检阶段",
    "FIVE_SECOND": "五秒倒计时",
    "IN_PROGRESS": "比赛中",
    "SETTLEMENT": "结算阶段",
}


class StateComponent(Component):
    """
    - 订阅一个主题，自动获取数据并渲染
    """
    topic: str = ""
    defaults: dict[str, Any] = {}

    def __init__(
        self,
        id: str,
        position: BlockPosition,
        grid: GridConfig,
        template: str,
        name: str | None = None,
    ):
        super().__init__(
            id=id,
            name=name or type(self).__name__,
            position=position,
            grid=grid,
            template=template,
            topics=(self.topic,),
        )

    def serialize(self, service: Any | None) -> dict[str, Any]:
        snapshot = _read_topic(service, self.topic)
        data = self.build_data(snapshot)
        return {
            "topic": self.topic,
            "data": data,
            "last_update": snapshot.get("_last_update"),
            "stale": _is_stale(snapshot),
        }

    def build_data(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        data = self.defaults.copy()
        data.update(_public_data(snapshot))
        return data


class GameStatusComponent(StateComponent):
    topic = "GameStatus"
    defaults = {
        "current_stage": MISSING_VALUE,
        "current_stage_label": MISSING_VALUE,
        "stage_countdown_sec": MISSING_VALUE,
        "red_score": MISSING_VALUE,
        "blue_score": MISSING_VALUE,
        "is_paused": MISSING_VALUE,
    }

    def build_data(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        data = super().build_data(snapshot)
        stage = data.get("current_stage")
        data["current_stage_label"] = GAME_STAGE_LABELS.get(stage, str(stage))
        data["is_paused"] = _bool_label(data.get("is_paused"))
        return data


class RobotDynamicStatusComponent(StateComponent):
    topic = "RobotDynamicStatus"
    defaults = {
        "current_health": MISSING_VALUE,
        "current_heat": MISSING_VALUE,
        "remaining_ammo": MISSING_VALUE,
        "current_chassis_energy": MISSING_VALUE,
        "current_buffer_energy": MISSING_VALUE,
        "is_out_of_combat": MISSING_VALUE,
        "out_of_combat_countdown": MISSING_VALUE,
    }

    def build_data(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        data = super().build_data(snapshot)
        data["is_out_of_combat"] = _bool_label(data.get("is_out_of_combat"))
        return data


class GlobalUnitStatusComponent(StateComponent):
    topic = "GlobalUnitStatus"
    defaults = {
        "base_health": MISSING_VALUE,
        "base_shield": MISSING_VALUE,
        "outpost_health": MISSING_VALUE,
        "enemy_base_health": MISSING_VALUE,
        "enemy_base_shield": MISSING_VALUE,
        "enemy_outpost_health": MISSING_VALUE,
        "total_damage_ally": MISSING_VALUE,
        "total_damage_enemy": MISSING_VALUE,
    }


def _read_topic(service: Any | None, topic: str) -> dict[str, Any]:
    if service is None:
        return {}
    try:
        data = service.get(topic)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _public_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if not key.startswith("_")}


def _is_stale(snapshot: dict[str, Any], max_age_sec: float = 2.0) -> bool:
    import time

    last_update = snapshot.get("_last_update")
    if not isinstance(last_update, (int, float)):
        return True
    return time.time() - float(last_update) > max_age_sec


def _bool_label(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value in (0, 1):
        return "是" if value == 1 else "否"
    return MISSING_VALUE if value is None else str(value)
