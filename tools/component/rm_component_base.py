import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BlockPosition(Enum):
    TOP_RIGHT = "right_up"
    BOTTOM_RIGHT = "right_down"
    BOTTOM_LEFT = "left_down"


@dataclass(frozen=True)
class GridConfig:
    """Component placement inside a dashboard region.

    start is zero-based: (0, 0) means the first row and first column.
    size is the number of rows and columns occupied by the component.
    """

    start: tuple[int, int]
    size: tuple[int, int]

    def validate(self) -> None:
        row, col = self.start
        row_span, col_span = self.size
        if row < 0 or col < 0:
            raise ValueError(f"grid.start 不能为负数: {self.start}")
        if row_span <= 0 or col_span <= 0:
            raise ValueError(f"grid.size 必须大于 0: {self.size}")

    def css_style(self) -> str:
        self.validate()
        row, col = self.start
        row_span, col_span = self.size
        row_start = row + 1
        col_start = col + 1
        return (
            f"grid-row: {row_start} / span {row_span}; "
            f"grid-column: {col_start} / span {col_span};"
        )


@dataclass
class Component:
    id: str
    name: str
    position: BlockPosition
    grid: GridConfig
    template: str
    topics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("component.id 不能为空")
        if not self.name:
            raise ValueError("component.name 不能为空")
        if not isinstance(self.position, BlockPosition):
            raise ValueError(f"未知的区块位置: {self.position}")
        if not self.template:
            raise ValueError("component.template 不能为空")
        self.grid.validate()

    def css_style(self) -> str:
        return self.grid.css_style()

    def render_context(self, service: Any | None) -> dict[str, Any]:
        return self.serialize(service)["data"]

    def serialize(self, service: Any | None) -> dict[str, Any]:
        topic = self.topics[0] if self.topics else None
        snapshot = _read_topic(service, topic)
        return {
            "topic": topic,
            "data": _public_data(snapshot),
            "last_update": snapshot.get("_last_update"),
            "stale": _is_stale(snapshot),
        }


def _read_topic(service: Any | None, topic: str | None) -> dict[str, Any]:
    if service is None or topic is None:
        return {}
    try:
        data = service.get(topic)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _public_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if not key.startswith("_")}


def _is_stale(snapshot: dict[str, Any], max_age_sec: float = 2.0) -> bool:
    last_update = snapshot.get("_last_update")
    if not isinstance(last_update, (int, float)):
        return True
    return time.time() - float(last_update) > max_age_sec
