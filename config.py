from pathlib import Path
from dataclasses import dataclass

# BASE_DIR = Path(__file__).parent

# LOG_DIR = BASE_DIR / "utils" / "logs_content"

# LOG_DIR.mkdir(exist_ok=True)

# RECORD_LOG = True

@dataclass(frozen=True)
class Config:
    """集中配置管理 - 单一职责：配置"""
    
    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000
    
    # MQTT 配置
    mqtt_host: str = "192.168.12.1"
    mqtt_port: int = 3333
    
    # UDP 视频配置
    video_udp_port: int = 3334
    video_max_frame_size: int = 1024 * 1024  # 1MB
    video_frame_timeout: int = 5  # 秒
    
    # WebSocket 配置
    ws_heartbeat_interval: int = 30  # 秒
    ws_connection_timeout: int = 60  # 秒
    
    # 消息队列配置
    message_queue_size: int = 1000
    
    # 日志配置
    BASE_DIR: Path = Path(__file__).parent
    LOG_DIR: Path = BASE_DIR / "tools" / "logs_content"
    LOG_DIR.mkdir(exist_ok=True)
    RECORD_LOG: bool = False
    LEVEL = "INFO"  # 可选: DEBUG, INFO, WARNING, ERROR, CRITICAL

    @property
    def mqtt_client_id(self) -> str:
        return f"custom_client_{self.port}"

    