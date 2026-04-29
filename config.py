from pathlib import Path
from dataclasses import dataclass, field

# BASE_DIR = Path(__file__).parent

# LOG_DIR = BASE_DIR / "utils" / "logs_content"

# LOG_DIR.mkdir(exist_ok=True)

# RECORD_LOG = True

@dataclass(frozen=True)
class Config:
    """集中配置管理 - 单一职责：配置"""
    
    # # 服务器配置
    # host: str = "0.0.0.0"
    # port: int = 8000
    
    # # MQTT 配置
    # mqtt_host: str = "192.168.12.1"
    # mqtt_port: int = 3333
    
    # # UDP 视频配置
    # video_udp_port: int = 3334
    # video_max_frame_size: int = 1024 * 1024  # 1MB
    # video_frame_timeout: int = 5  # 秒
    
    # # WebSocket 配置
    # ws_heartbeat_interval: int = 30  # 秒
    # ws_connection_timeout: int = 60  # 秒
    
    # # 消息队列配置
    # message_queue_size: int = 1000
    
    # 日志配置
    IF_LOG: bool = True
    BASE_DIR: Path = Path(__file__).parent
    LOG_DIR: Path = BASE_DIR / "tools" / "logs_content"
    LOG_DIR.mkdir(exist_ok=True)
    RECORD_LOG: bool = False
    LEVEL: str = "INFO"  # 可选: DEBUG, INFO, WARNING, ERROR, CRITICAL

    # @property
    # def mqtt_client_id(self) -> str:
    #     return f"custom_client_{self.port}"

# @dataclass(frozen=True)
# class WebConfig:
#     """
#      - 配置网格
#      - 配置网格内部的组件
#     """
#     Grid: dict[str, tuple[int, int]] = ({"left-down": (2, 6), "right-down": (2, 2), "right-up": (4, 2)})
#     Components: dict[str, str] = {}

@dataclass
class GridConfig:
    """
     - 右上，右下，左下
     - 每个区域的行列数
     - 每个区域的组件列表
    """
    right_up: tuple[int, int] = (4, 2)
    right_down: tuple[int, int] = (2, 2)
    left_down: tuple[int, int] = (2, 6)
    # components: dict[str, list[str]] = field(default_factory=dict)  # 组件列表，按区域划分

    # def __post_init__(self):
    #     # 计算列宽和行高的 CSS 样式字符串
    #     self.column_widths = self._calculate_column_widths()
    #     self.row_heights = self._calculate_row_heights()

    # def _get_raw_html_widths(self, area: str) -> str:
    #     return f"grid-template-columns: repeat({getattr(self, area)[1]}, 1fr); grid-template-rows: repeat({getattr(self, area)[0]}, 1fr);"
    
    def _calculate_column_widths(self, area: str) -> str:
        # 以右上区域为例，其他区域可类似处理
        return f"repeat({getattr(self, area)[1]}, 1fr);"

    def _calculate_row_heights(self, area: str) -> str:
        # 以右上区域为例，其他区域可类似处理
        return f"repeat({getattr(self, area)[0]}, 1fr);"

    @property
    def right_up_column_widths(self) -> str:
        return self._calculate_column_widths("right_up")
    
    @property
    def right_up_row_heights(self) -> str:
        return self._calculate_row_heights("right_up")

    @property
    def right_down_column_widths(self) -> str:
        return self._calculate_column_widths("right_down")
    
    @property
    def right_down_row_heights(self) -> str:
        return self._calculate_row_heights("right_down")
    
    @property
    def left_down_column_widths(self) -> str:
        return self._calculate_column_widths("left_down")
    
    @property
    def left_down_row_heights(self) -> str:
        return self._calculate_row_heights("left_down")




if __name__ == "__main__":
    grid_config = GridConfig()
    print(grid_config.right_up_column_widths, grid_config.right_up_row_heights)