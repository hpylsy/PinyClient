import struct
from typing import Any, cast
from enum import IntEnum
from dataclasses import dataclass, field

from .base import BaseMessage
from .protocol import messages_pb2 as pb_mes

_pb = cast(Any, pb_mes)  # 避免pyright对protobuf模块的类型检查错误
FRAME_PACK_FORMAT = '>HHI' # 帧编号（2 byte）当前帧内分片序号（2 byte）当前帧总字节数（4 byte）

# =============================================
# 枚举类型（统一集中）
# =============================================
class GameStage(IntEnum):
    """比赛阶段枚举（GameStatus.current_stage）。"""
    NOT_STARTED = 0
    PREPARATION = 1
    SELF_CHECK = 2
    FIVE_SECOND = 3
    IN_PROGRESS = 4
    SETTLEMENT = 5


class BaseStatus(IntEnum):
    """基地状态枚举（GlobalUnitStatus.base_status / enemy_base_status）。"""
    INVINCIBLE = 0
    ARMOR_RETRACTED = 1
    ARMOR_DEPLOYED = 2


class OutpostStatus(IntEnum):
    """前哨站状态枚举（GlobalUnitStatus.outpost_status / enemy_outpost_status）。"""
    INVINCIBLE = 0
    ROTATING = 1
    STOPPED = 2
    DESTROYED_NO_REBUILD = 3
    DESTROYED_CAN_REBUILD = 4
    DESTROYED_REBUILDING = 5


class MechanismId(IntEnum):
    """全局特殊机制 ID（GlobalSpecialMechanism.mechanism_id）。"""
    ALLY_FORT_OCCUPIED = 1
    ENEMY_FORT_OCCUPIED = 2


class EventId(IntEnum):
    """全局事件 ID（Event.event_id）。"""
    KILL = 1
    BASE_OUTPOST_DESTROYED = 2
    RUNE_ACTIVATION_COUNT = 3
    RUNE_ACTIVATING = 4
    RUNE_ACTIVATED_ARMS = 5
    RUNE_ACTIVATED = 6
    HERO_ENTER_DEPLOY = 7
    HERO_SNIPER_DAMAGE_ALLY = 8
    HERO_SNIPER_DAMAGE_ENEMY = 9
    AIR_SUPPORT_CALLED_ALLY = 10
    AIR_SUPPORT_INTERRUPTED_ALLY = 11
    AIR_SUPPORT_CALLED_ENEMY = 12
    AIR_SUPPORT_INTERRUPTED_ENEMY = 13
    DART_HIT = 14
    DART_GATE_OPENED = 15
    BASE_UNDER_ATTACK = 16
    OUTPOST_STOPPED = 17
    BASE_ARMOR_DEPLOYED = 18


class TechCoreStatus(IntEnum):
    """科技核心状态（TechCoreMotionStateSync.status）。"""
    NOT_ASSEMBLING = 1
    MOVING = 2
    READY_FIRST_STEP = 3
    READY_NEXT_STEP = 4
    ALL_STEPS_DONE = 5
    CONFIRMING = 6


class EnemyCoreStatus(IntEnum):
    """对方科技核心状态（TechCoreMotionStateSync.enemy_core_status）。"""
    NO_ASSEMBLY = 0
    ASSEMBLING_NON_LEVEL4 = 1
    ASSEMBLING_LEVEL4 = 2


class SentryControlMode(IntEnum):
    """哨兵控制方式（RobotPerformanceSelectionCommand/Sync.sentry_control）。"""
    AUTO = 0
    SEMI_AUTO = 1


class DeployModeStatus(IntEnum):
    """英雄部署状态（DeployModeStatusSync.status）。"""
    NOT_DEPLOYED = 0
    DEPLOYED = 1


class RuneStatus(IntEnum):
    """能量机关状态（RuneStatusSync.rune_status）。"""
    INACTIVE = 1
    ACTIVATING = 2
    ACTIVATED = 3


class SentryPosture(IntEnum):
    """哨兵姿态（SentryStatusSync.posture_id）。"""
    ATTACK = 1
    DEFENSE = 2
    MOVE = 3


class DartGateStatus(IntEnum):
    """飞镖闸门状态（DartSelectTargetStatusSync.open）。"""
    CLOSED = 0
    OPENING = 1
    OPENED = 2


class AirSupportStatus(IntEnum):
    """空中支援状态（AirSupportStatusSync.airsupport_status）。"""
    NOT_ACTIVE = 0
    ACTIVE = 1


class ShooterStatus(IntEnum):
    """发射机构状态（AirSupportStatusSync.shooter_status）。"""
    LOCKED = 0
    NORMAL = 1


class ConnectionState(IntEnum):
    """连接状态（RobotStaticStatus.connection_state）。"""
    DISCONNECTED = 0
    CONNECTED = 1


class FieldState(IntEnum):
    """上场状态（RobotStaticStatus.field_state）。"""
    ON_FIELD = 0
    OFF_FIELD = 1


class AliveState(IntEnum):
    """存活状态（RobotStaticStatus.alive_state）。"""
    UNKNOWN = 0
    ALIVE = 1
    DEAD = 2


class ShooterPerformance(IntEnum):
    """发射机构性能体系（RobotStaticStatus.performance_system_shooter）。"""
    COOLING_PRIORITY = 1
    BURST_PRIORITY = 2
    HERO_MELEE = 3
    HERO_RANGED = 4


class ChassisPerformance(IntEnum):
    """底盘性能体系（RobotStaticStatus.performance_system_chassis）。"""
    HEALTH_PRIORITY = 1
    POWER_PRIORITY = 2
    HERO_MELEE = 3
    HERO_RANGED = 4


class ModuleStatus(IntEnum):
    """模块状态（RobotModuleStatus.*）。"""
    OFFLINE = 0
    ONLINE = 1
    INSTALLATION_ERROR = 2


class BuffType(IntEnum):
    """Buff 类型（Buff.buff_type）。"""
    ATTACK = 1
    DEFENSE = 2
    COOLING = 3
    CHASSIS_POWER = 4
    HEALTH_REGEN = 5
    AMMO_EXCHANGE = 6
    TERRAIN_CROSS = 7


class PenaltyType(IntEnum):
    """判罚类型（PenaltyInfo.penalty_type）。"""
    YELLOW_CARD = 1
    BOTH_YELLOW_CARD = 2
    RED_CARD = 3
    OVER_POWER = 4
    OVER_HEAT = 5
    OVER_SPEED = 6


class SentryIntention(IntEnum):
    """哨兵意图（RobotPathPlanInfo.intention）。"""
    ATTACK = 1
    DEFEND = 2
    MOVE = 3


class HighlightType(IntEnum):
    """雷达高亮标识（RadarInfoToClient.is_high_light）。"""
    NO = 0
    YES = 1
    YES_OFFLINE = 2


class SendScope(IntEnum):
    """地图标记发送范围（MapClickInfoNotify.is_send_all）。"""
    SPECIFIED_CLIENT = 0
    EXCLUDE_SENTRY = 1
    INCLUDE_SENTRY = 2


class MapMarkMode(IntEnum):
    """地图标记类型（MapClickInfoNotify.mode）。"""
    ATTACK = 1
    DEFENSE = 2
    WARNING = 3
    CUSTOM = 4


class MapMarkType(IntEnum):
    """地图标记模式（MapClickInfoNotify.type）。"""
    MAP = 1
    ENEMY_ROBOT = 2


class AssemblyOperation(IntEnum):
    """装配操作（AssemblyCommand.operation）。"""
    CONFIRM = 1
    CANCEL = 2


class CommonCmdType(IntEnum):
    """常用指令类型（CommonCommand.cmd_type）。"""
    EXCHANGE_17MM_AMMO = 1
    EXCHANGE_42MM_AMMO = 2
    CONFIRM_RESPAWN = 3
    EXCHANGE_INSTANT_RESPAWN = 4
    REMOTE_EXCHANGE_AMMO = 5
    REMOTE_EXCHANGE_HEALTH = 6


class DeployMode(IntEnum):
    """英雄部署模式指令（HeroDeployModeEventCommand.mode）。"""
    EXIT = 0
    ENTER = 1


class DartTarget(IntEnum):
    """飞镖目标 ID（DartCommand.target_id）。"""
    OUTPOST = 1
    BASE_FIXED = 2
    BASE_RANDOM_FIXED = 3
    BASE_RANDOM_MOVING = 4
    BASE_END_MOVING = 5


class SentryCtrlCmd(IntEnum):
    """哨兵控制指令编号（SentryCtrlCommand.command_id）。"""
    HEAL_AT_POINT = 1
    AMMO_AT_STATION = 2
    REMOTE_AMMO = 3
    REMOTE_HEAL = 4
    CONFIRM_RESPAWN = 5
    PAY_FOR_RESPAWN = 6
    MAP_MARK = 7
    SWITCH_ATTACK = 8
    SWITCH_DEFENSE = 9
    SWITCH_MOVE = 10


class AirSupportCmd(IntEnum):
    """空中支援指令类型（AirSupportCommand.command_id）。"""
    FREE_CALL = 1
    PAID_CALL = 2
    INTERRUPT = 3


# =============================================
# 数据类（统一集中）
# =============================================
@dataclass
class KeyboardMouseControl(BaseMessage):
    """2.2.1 键鼠控制：自定义客户端 -> 机器人（图传链路）。"""
    mouse_x: int = 0
    mouse_y: int = 0
    mouse_z: int = 0
    left_button_down: bool = False
    right_button_down: bool = False
    keyboard_value: int = 0
    mid_button_down: bool = False
    PB_CLASS = _pb.KeyboardMouseControl


@dataclass
class CustomControl(BaseMessage):
    """2.2.2 自定义数据（最大 30 字节）：自定义客户端 -> 机器人。"""
    data: bytes = b""
    PB_CLASS = _pb.CustomControl


@dataclass
class MapClickInfoNotify(BaseMessage):
    """2.2.17 地图点击标记：自定义客户端 -> 服务器。"""
    is_send_all: SendScope = SendScope.SPECIFIED_CLIENT
    robot_id: bytes = b""
    mode: MapMarkMode = MapMarkMode.ATTACK
    enemy_id: int = 0
    ascii: int = 0
    type: MapMarkType = MapMarkType.MAP
    screen_x: int = 0
    screen_y: int = 0
    map_x: float = 0.0
    map_y: float = 0.0
    PB_CLASS = _pb.MapClickInfoNotify


@dataclass
class AssemblyCommand(BaseMessage):
    """2.2.20 工程装配指令：自定义客户端 -> 服务器。"""
    operation: AssemblyOperation = AssemblyOperation.CONFIRM
    difficulty: int = 0
    PB_CLASS = _pb.AssemblyCommand


@dataclass
class RobotPerformanceSelectionCommand(BaseMessage):
    """2.2.22 性能体系/控制方式选择：自定义客户端 -> 服务器。"""
    shooter: int = 0
    chassis: int = 0
    sentry_control: SentryControlMode = SentryControlMode.AUTO
    PB_CLASS = _pb.RobotPerformanceSelectionCommand


@dataclass
class CommonCommand(BaseMessage):
    """2.2.24 常用指令：自定义客户端 -> 服务器。"""
    cmd_type: CommonCmdType = CommonCmdType.EXCHANGE_17MM_AMMO
    param: int = 0
    PB_CLASS = _pb.CommonCommand


@dataclass
class HeroDeployModeEventCommand(BaseMessage):
    """2.2.25 英雄部署模式指令：自定义客户端 -> 服务器。"""
    mode: DeployMode = DeployMode.EXIT
    PB_CLASS = _pb.HeroDeployModeEventCommand


@dataclass
class RuneActivateCommand(BaseMessage):
    """2.2.27 能量机关激活指令：自定义客户端 -> 服务器。"""
    activate: int = 0
    PB_CLASS = _pb.RuneActivateCommand


@dataclass
class DartCommand(BaseMessage):
    """2.2.30 飞镖控制指令：自定义客户端 -> 服务器。"""
    target_id: DartTarget = DartTarget.OUTPOST
    open: bool = False
    launch_confirm: bool = False
    PB_CLASS = _pb.DartCommand


@dataclass
class SentryCtrlCommand(BaseMessage):
    """2.2.32 哨兵控制指令请求：自定义客户端 -> 服务器。"""
    command_id: SentryCtrlCmd = SentryCtrlCmd.HEAL_AT_POINT
    PB_CLASS = _pb.SentryCtrlCommand


@dataclass
class AirSupportCommand(BaseMessage):
    """2.2.34 空中支援指令：自定义客户端 -> 服务器。"""
    command_id: AirSupportCmd = AirSupportCmd.FREE_CALL
    PB_CLASS = _pb.AirSupportCommand

@dataclass
class GameStatus(BaseMessage):
    """2.2.3 比赛全局状态：服务器 -> 自定义客户端。"""
    current_round: int = 0
    total_rounds: int = 0
    red_score: int = 0
    blue_score: int = 0
    current_stage: GameStage = GameStage.NOT_STARTED
    stage_countdown_sec: int = 0
    stage_elapsed_sec: int = 0
    is_paused: bool = False
    PB_CLASS = _pb.GameStatus

    @property
    def is_match_running(self) -> bool:
        return self.current_stage == GameStage.IN_PROGRESS

    @property
    def is_preparation(self) -> bool:
        return self.current_stage == GameStage.PREPARATION

    @property
    def remaining_seconds(self) -> int:
        if self.current_stage == GameStage.IN_PROGRESS:
            return self.stage_countdown_sec
        return 0


@dataclass
class GlobalUnitStatus(BaseMessage):
    """2.2.4 基地/前哨站/机器人状态：服务器 -> 自定义客户端。"""
    base_health: int = 0
    base_status: BaseStatus = BaseStatus.INVINCIBLE
    base_shield: int = 0
    outpost_health: int = 0
    outpost_status: OutpostStatus = OutpostStatus.INVINCIBLE
    enemy_base_health: int = 0
    enemy_base_status: BaseStatus = BaseStatus.INVINCIBLE
    enemy_base_shield: int = 0
    enemy_outpost_health: int = 0
    enemy_outpost_status: OutpostStatus = OutpostStatus.INVINCIBLE
    robot_health: list[int] = field(default_factory=list)
    robot_bullets: list[int] = field(default_factory=list)
    total_damage_ally: int = 0
    total_damage_enemy: int = 0
    PB_CLASS = _pb.GlobalUnitStatus


@dataclass
class GlobalLogisticsStatus(BaseMessage):
    """2.2.5 全局后勤信息：服务器 -> 自定义客户端。"""
    remaining_economy: int = 0
    total_economy_obtained: int = 0
    tech_level: int = 0
    encryption_level: int = 0
    PB_CLASS = _pb.GlobalLogisticsStatus


@dataclass
class GlobalSpecialMechanism(BaseMessage):
    """2.2.6 全局特殊机制：服务器 -> 自定义客户端。"""
    mechanism_id: list[int] = field(default_factory=list)
    mechanism_time_sec: list[int] = field(default_factory=list)
    PB_CLASS = _pb.GlobalSpecialMechanism


@dataclass
class Event(BaseMessage):
    """2.2.7 全局事件通知：服务器 -> 自定义客户端。"""
    event_id: EventId = EventId.KILL
    param: str = ""
    PB_CLASS = _pb.Event


@dataclass
class RobotInjuryStat(BaseMessage):
    """2.2.8 单次存活受伤统计：服务器 -> 自定义客户端。"""
    total_damage: int = 0
    collision_damage: int = 0
    small_projectile_damage: int = 0
    large_projectile_damage: int = 0
    dart_splash_damage: int = 0
    module_offline_damage: int = 0
    offline_damage: int = 0
    penalty_damage: int = 0
    server_kill_damage: int = 0
    killer_id: int = 0
    PB_CLASS = _pb.RobotInjuryStat


@dataclass
class RobotRespawnStatus(BaseMessage):
    """2.2.9 复活状态同步：服务器 -> 自定义客户端。"""
    is_pending_respawn: bool = False
    total_respawn_progress: int = 0
    current_respawn_progress: int = 0
    can_free_respawn: bool = False
    gold_cost_for_respawn: int = 0
    can_pay_for_respawn: bool = False
    PB_CLASS = _pb.RobotRespawnStatus


@dataclass
class RobotStaticStatus(BaseMessage):
    """2.2.10 机器人固定属性与配置：服务器 -> 自定义客户端。"""
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    field_state: FieldState = FieldState.ON_FIELD
    alive_state: AliveState = AliveState.UNKNOWN
    robot_id: int = 0
    robot_type: int = 0
    performance_system_shooter: ShooterPerformance = ShooterPerformance.COOLING_PRIORITY
    performance_system_chassis: ChassisPerformance = ChassisPerformance.HEALTH_PRIORITY
    level: int = 0
    max_health: int = 0
    max_heat: int = 0
    heat_cooldown_rate: float = 0.0
    max_power: int = 0
    max_buffer_energy: int = 0
    max_chassis_energy: int = 0
    PB_CLASS = _pb.RobotStaticStatus


@dataclass
class RobotDynamicStatus(BaseMessage):
    """2.2.11 机器人实时状态：服务器 -> 自定义客户端。"""
    current_health: int = 0
    current_heat: float = 0.0
    last_projectile_fire_rate: float = 0.0
    current_chassis_energy: int = 0
    current_buffer_energy: int = 0
    current_experience: int = 0
    experience_for_upgrade: int = 0
    total_projectiles_fired: int = 0
    remaining_ammo: int = 0
    is_out_of_combat: bool = False
    out_of_combat_countdown: int = 0
    can_remote_heal: bool = False
    can_remote_ammo: bool = False
    PB_CLASS = _pb.RobotDynamicStatus


@dataclass
class RobotModuleStatus(BaseMessage):
    """2.2.12 机器人模块运行状态：服务器 -> 自定义客户端。"""
    power_manager: ModuleStatus = ModuleStatus.OFFLINE
    rfid: ModuleStatus = ModuleStatus.OFFLINE
    light_strip: ModuleStatus = ModuleStatus.OFFLINE
    small_shooter: ModuleStatus = ModuleStatus.OFFLINE
    big_shooter: ModuleStatus = ModuleStatus.OFFLINE
    uwb: ModuleStatus = ModuleStatus.OFFLINE
    armor: ModuleStatus = ModuleStatus.OFFLINE
    video_transmission: ModuleStatus = ModuleStatus.OFFLINE
    capacitor: ModuleStatus = ModuleStatus.OFFLINE
    main_controller: ModuleStatus = ModuleStatus.OFFLINE
    laser_detection_module: ModuleStatus = ModuleStatus.OFFLINE
    PB_CLASS = _pb.RobotModuleStatus


@dataclass
class RobotPosition(BaseMessage):
    """2.2.13 机器人空间坐标与朝向：服务器 -> 自定义客户端。"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    PB_CLASS = _pb.RobotPosition


@dataclass
class Buff(BaseMessage):
    """2.2.14 Buff 信息：服务器 -> 自定义客户端。"""
    robot_id: int = 0
    buff_type: BuffType = BuffType.ATTACK
    buff_level: int = 0
    buff_max_time: int = 0
    buff_left_time: int = 0
    PB_CLASS = _pb.Buff


@dataclass
class PenaltyInfo(BaseMessage):
    """2.2.15 判罚信息：服务器 -> 自定义客户端。"""
    penalty_type: PenaltyType = PenaltyType.YELLOW_CARD
    penalty_effect_sec: int = 0
    total_penalty_num: int = 0
    PB_CLASS = _pb.PenaltyInfo


@dataclass
class RobotPathPlanInfo(BaseMessage):
    """2.2.16 哨兵轨迹规划信息：服务器 -> 自定义客户端。"""
    intention: SentryIntention = SentryIntention.ATTACK
    start_pos_x: int = 0
    start_pos_y: int = 0
    offset_x: list[int] = field(default_factory=list)
    offset_y: list[int] = field(default_factory=list)
    sender_id: int = 0
    PB_CLASS = _pb.RobotPathPlanInfo


@dataclass
class RadarInfoToClient(BaseMessage):
    """2.2.18 雷达机器人位置信息：服务器 -> 自定义客户端。"""
    target_robot_id: int = 0
    target_pos_x: float = 0.0
    target_pos_y: float = 0.0
    torward_angle: float = 0.0
    is_high_light: HighlightType = HighlightType.NO
    PB_CLASS = _pb.RadarInfoToClient


@dataclass
class CustomByteBlock(BaseMessage):
    """2.2.19 机器人自定义上传数据流：机器人 -> 自定义客户端。"""
    data: bytes = b""
    PB_CLASS = _pb.CustomByteBlock


@dataclass
class TechCoreMotionStateSync(BaseMessage):
    """2.2.21 科技核心运动状态：服务器 -> 自定义客户端。"""
    maximum_difficulty_level: int = 0
    status: TechCoreStatus = TechCoreStatus.NOT_ASSEMBLING
    enemy_core_status: EnemyCoreStatus = EnemyCoreStatus.NO_ASSEMBLY
    remain_time_all: int = 0
    remain_time_step: int = 0
    PB_CLASS = _pb.TechCoreMotionStateSync


@dataclass
class RobotPerformanceSelectionSync(BaseMessage):
    """2.2.23 性能体系状态同步：服务器 -> 自定义客户端。"""
    shooter: int = 0
    chassis: int = 0
    sentry_control: SentryControlMode = SentryControlMode.AUTO
    PB_CLASS = _pb.RobotPerformanceSelectionSync


@dataclass
class DeployModeStatusSync(BaseMessage):
    """2.2.26 英雄部署模式状态：服务器 -> 自定义客户端。"""
    status: DeployModeStatus = DeployModeStatus.NOT_DEPLOYED
    PB_CLASS = _pb.DeployModeStatusSync


@dataclass
class RuneStatusSync(BaseMessage):
    """2.2.28 能量机关状态同步：服务器 -> 自定义客户端。"""
    rune_status: RuneStatus = RuneStatus.INACTIVE
    activated_arms: int = 0
    average_rings: int = 0
    PB_CLASS = _pb.RuneStatusSync


@dataclass
class SentryStatusSync(BaseMessage):
    """2.2.29 哨兵姿态/弱化状态：服务器 -> 自定义客户端。"""
    posture_id: SentryPosture = SentryPosture.ATTACK
    is_weakened: bool = False
    PB_CLASS = _pb.SentryStatusSync


@dataclass
class DartSelectTargetStatusSync(BaseMessage):
    """2.2.31 飞镖目标选择状态：服务器 -> 自定义客户端。"""
    target_id: int = 0
    open: DartGateStatus = DartGateStatus.CLOSED
    PB_CLASS = _pb.DartSelectTargetStatusSync


@dataclass
class SentryCtrlResult(BaseMessage):
    """2.2.33 哨兵控制结果反馈：服务器 -> 自定义客户端。"""
    command_id: int = 0
    result_code: int = 0
    PB_CLASS = _pb.SentryCtrlResult


@dataclass
class AirSupportStatusSync(BaseMessage):
    """2.2.35 空中支援状态反馈：服务器 -> 自定义客户端。"""
    airsupport_status: AirSupportStatus = AirSupportStatus.NOT_ACTIVE
    left_time: int = 0
    cost_coins: int = 0
    is_being_targeted: int = 0
    shooter_status: ShooterStatus = ShooterStatus.LOCKED
    PB_CLASS = _pb.AirSupportStatusSync

# =============================================
# 自定义类
# =============================================

class MqttUdpPackage(CustomByteBlock):
    def parse(self):
        """解析UDP数据包并返回状态"""
        if len(self.data) != 300:
            raise ValueError("数据包长度!=300字节，数据包不完整")
        actual_len = int.from_bytes(self.data[0:2], byteorder='little') 
        payload = self.data[2:2+actual_len]
        return (actual_len, payload)

class NormalUDPPackage:
    def __init__(self, data: bytes):
        self.data = data
    
    def parse(self) -> tuple[int, int, int, bytes]:
        """解析UDP数据包并返回状态"""
        # 帧编号（2 byte）当前帧内分片序号（2 byte）当前帧总字节数（4 byte）
        frame_id, chunk_id, total_length = struct.unpack(FRAME_PACK_FORMAT, self.data[:8])
        return (frame_id, chunk_id, total_length, self.data[8:])

# =============================================
# 主题名到消息类的映射（统一集中）
# =============================================

TOPIC2MSG: dict[str, type[BaseMessage]] = {
    # 比赛状态机类
    "GameStatus": GameStatus,
    "GlobalUnitStatus": GlobalUnitStatus,
    "GlobalLogisticsStatus": GlobalLogisticsStatus,
    "GlobalSpecialMechanism": GlobalSpecialMechanism,
    "Event": Event,
    # 机器人类
    "RobotInjuryStat": RobotInjuryStat,
    "RobotRespawnStatus": RobotRespawnStatus,
    "RobotStaticStatus": RobotStaticStatus,
    "RobotDynamicStatus": RobotDynamicStatus,
    "RobotModuleStatus": RobotModuleStatus,
    "RobotPosition": RobotPosition,
    "Buff": Buff,
    "PenaltyInfo": PenaltyInfo,
    "RobotPathPlanInfo": RobotPathPlanInfo,
    "RadarInfoToClient": RadarInfoToClient,
    # 自定义数据类
    "CustomByteBlock": CustomByteBlock,
    "KeyboardMouseControl": KeyboardMouseControl,
    "CustomControl": CustomControl,
    # 同步类
    "TechCoreMotionStateSync": TechCoreMotionStateSync,
    "RobotPerformanceSelectionSync": RobotPerformanceSelectionSync,
    "DeployModeStatusSync": DeployModeStatusSync,
    "RuneStatusSync": RuneStatusSync,
    "SentryStatusSync": SentryStatusSync,
    "DartSelectTargetStatusSync": DartSelectTargetStatusSync,
    "SentryCtrlResult": SentryCtrlResult,
    "AirSupportStatusSync": AirSupportStatusSync,
    # command类
    "MapClickInfoNotify": MapClickInfoNotify,
    "AssemblyCommand": AssemblyCommand,
    "RobotPerformanceSelectionCommand": RobotPerformanceSelectionCommand,
    "CommonCommand": CommonCommand,
    "HeroDeployModeEventCommand": HeroDeployModeEventCommand,
    "RuneActivateCommand": RuneActivateCommand,
    "DartCommand": DartCommand,
    "SentryCtrlCommand": SentryCtrlCommand,
    "AirSupportCommand": AirSupportCommand,
    # 图传链路类
    "KeyboardMouseControl": KeyboardMouseControl,
    "CustomControl": CustomControl,
    "CustomByteBlock": MqttUdpPackage,
}


def get_message_class(topic: str) -> type[BaseMessage]:
    """根据主题名获取对应的消息类。"""
    if topic not in TOPIC2MSG:
        raise ValueError(f"未知的主题名: {topic}")
    return TOPIC2MSG[topic]


if __name__ == "__main__":
    g = get_message_class("GameStatus")()
    g_state = {
        "current_round": 1,
        "total_rounds": 3,
        "red_score": 0,
        "blue_score": 0,
        "current_stage": 4,
        "stage_countdown_sec": 120,
        "stage_elapsed_sec": 0,
        "is_paused": False
    }
    print("1. 测试GameStatus基本属性")
    print("主题名",g.topic())
    print("2. 测试从字典创建GameStatus对象+访问属性")
    g.from_dict(g_state)
    print("创建的GameStatus对象:", g)
    print("属性测试:", g.current_stage)
    print("字典", g.to_dict())
    print("protobuf", g.to_protobuf())
    print("json", g.to_json())
    g2 = GameStatus()
    g2_state = {
        "current_round": 2,
        "total_rounds": 23,
        "red_score": 2,
        "blue_score": 2,
        "current_stage":2,
        "stage_countdown_sec": 222,
        "stage_elapsed_sec": 2,
        "is_paused": True
    }
    g2.from_dict(g2_state)
    g3 = GameStatus()
    g3.from_dict(g_state)
    g.from_protobuf(g2.to_protobuf())
    print("g after protobuf:", g)
    g.from_json(g3.to_json())
    print("g after json:", g)
