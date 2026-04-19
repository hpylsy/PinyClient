from __future__ import annotations
from enum import Enum
from dataclasses import dataclass

# ============================================================
# 常量
# ============================================================
TOTAL_TIME = 420  # 比赛总时长，单位为秒
ALL_STATES = "ALL_STATES"


UNKNOWN = 0
ALLY = "ALLY"
ENEMY = "ENEMY"
ALL_SIDES = "ALL_SIDES"

# RED = "RED"
# BLUE = "BLUE"
class Sides(Enum):
    UNKNOWN = UNKNOWN
    RED = 1
    BLUE = 2
    
# BASE = "BASE"
# OUTPOST = "OUTPOST"
# ALL_BUILDINGS = "ALL_BUILDINGS"
class BuildingTypes(Enum):
    UNKNOWN = UNKNOWN
    BASE = 1
    OUTPOST = 2

HEALTH = "HEALTH"
STATUS = "STATUS"
SHIELD = "SHIELD"

# HERO = "HERO"
# ENGINEER = "ENGINEER"
# INFANTRY = "INFANTRY"
# AIR = "AIR"
# SENTRY = "SENTRY"
# DART = "DART"
# RADAR = "RADAR"
class RobotTypes(Enum):
    UNKNOWN = UNKNOWN
    HERO = 1
    ENGINEER = 2
    INFANTRY = 3
    AIR = 4
    SENTRY = 5
    DART = 6
    RADAR = 7

@dataclass
class PlayerTypes:
    Side: Sides = Sides.UNKNOWN
    Robot: RobotTypes = RobotTypes.UNKNOWN
    Infantry_Select: int = 0  # 仅当 Robot 是 INFANTRY 时有效，表示三名步兵中的哪一名被选中（1、2 或 3）

    def get_cli_id(self) -> int:
        """根据玩家类型获取对应的 MQTT client_id。"""
        if self.Side == Sides.UNKNOWN or self.Robot == RobotTypes.UNKNOWN:
            raise ValueError(f"无法获取 client_id，因为玩家类型不完整: {self}")
        
        # 构建机器人名称
        color_prefix = self.Side.name
        robot_suffix = self.Robot.name
        robot_name: str = f"{color_prefix}_{robot_suffix}"
        
        # 获取 client_id
        res = get_cli_id_by_name(robot_name)
        if isinstance(res, tuple):
            if self.Robot != RobotTypes.INFANTRY:
                raise ValueError(f"机器人 {robot_name} 对应多个 client_id，但玩家类型中 Robot 不是 INFANTRY: {self}")
            if self.Infantry_Select not in (1, 2, 3):
                raise ValueError(f"玩家类型中 Infantry_Select 必须是 1、2 或 3，但得到的是 {self.Infantry_Select}: {self}")
            return res[self.Infantry_Select - 1]  # 根据选择返回对应的 client_id
        else:
            return res
    
    def get_id(self) -> int | tuple[int, ...]:
        """根据玩家类型获取对应的数字 ID。"""
        # TODO: 可以和上面的 get_cli_id 方法合并，统一为一个根据名称获取属性的方法，减少重复代码。
        if self.Side == Sides.UNKNOWN or self.Robot == RobotTypes.UNKNOWN:
            raise ValueError(f"无法获取数字 ID，因为玩家类型不完整: {self}")
        
        # 构建机器人名称
        color_prefix = self.Side.name
        robot_suffix = self.Robot.name
        robot_name: str = f"{color_prefix}_{robot_suffix}"
        
        # 获取数字 ID
        res = get_id_by_name(robot_name)
        if isinstance(res, tuple):
            if self.Robot != RobotTypes.INFANTRY:
                raise ValueError(f"机器人 {robot_name} 对应多个数字 ID，但玩家类型中 Robot 不是 INFANTRY: {self}")
            if self.Infantry_Select not in (1, 2, 3):
                raise ValueError(f"玩家类型中 Infantry_Select 必须是 1、2 或 3，但得到的是 {self.Infantry_Select}: {self}")
            return res[self.Infantry_Select - 1]  # 根据选择返回对应的数字 ID
        else:
            return res

RED_HERO = "RED_HERO"
RED_ENGINEER = "RED_ENGINEER"
RED_INFANTRY = "RED_INFANTRY"
RED_AIR = "RED_AIR"
RED_SENTRY = "RED_SENTRY"
RED_DART = "RED_DART"
RED_RADAR = "RED_RADAR"
RED_OUTPOST = "RED_OUTPOST"
RED_BASE = "RED_BASE"

BLUE_HERO = "BLUE_HERO"
BLUE_ENGINEER = "BLUE_ENGINEER"
BLUE_INFANTRY = "BLUE_INFANTRY"
BLUE_AIR = "BLUE_AIR"
BLUE_SENTRY = "BLUE_SENTRY"
BLUE_DART = "BLUE_DART"
BLUE_RADAR = "BLUE_RADAR"
BLUE_OUTPOST = "BLUE_OUTPOST"
BLUE_BASE = "BLUE_BASE"

REFREE_SERVER = "REFREE_SERVER"
# ============================================================
# 机器人 ID 映射
# ============================================================
# ID_TO_NAME: 机器人数字 ID (1, 2, 3...) -> 名称 (RED_HERO, RED_ENGINEER...)
# 用于裁判系统下发消息中的 robot_id 字段

def reverse(d: dict[str, int | tuple[int, ...]]) -> dict[int, str]:
    """将名称 -> ID 的映射反转为 ID -> 名称 的映射，支持 ID 是单个整数或整数元组的情况。"""
    reversed_dict: dict[int, str] = {}
    for name, ids in d.items():
        if isinstance(ids, tuple):
            for id_ in ids:
                reversed_dict[id_] = name
        else:
            reversed_dict[ids] = name
    return reversed_dict

NAME_TO_ID: dict[str, int | tuple[int, ...]] = {
    RED_HERO: 1,
    RED_ENGINEER: 2,
    RED_INFANTRY: (3, 4, 5),
    RED_AIR: 6,
    RED_SENTRY: 7,
    RED_DART: 8,
    RED_RADAR: 9,
    RED_OUTPOST: 10,
    RED_BASE: 11,

    BLUE_HERO: 101,
    BLUE_ENGINEER: 102,
    BLUE_INFANTRY: (103, 104, 105),
    BLUE_AIR: 106,
    BLUE_SENTRY: 107,
    BLUE_DART: 108,
    BLUE_RADAR: 109,
    BLUE_OUTPOST: 110,
    BLUE_BASE: 111,
    # REFREE_SERVER: 107,
}

# NAME_TO_ID: 名称 -> 数字 ID 的反向映射
ID_TO_NAME: dict[str, int | tuple[int, ...]] = reverse(NAME_TO_ID)

# CLIENT_ID_TO_NAME: 选手端十六进制 ID (0x0101, 0x0102...) -> 名称
# 用于 MQTT client_id 连接参数
NAME_TO_CLIENT_ID: dict[str, int | tuple[int, ...]] = {
    RED_HERO: 0x0101,
    RED_ENGINEER: 0x0102,
    RED_INFANTRY: (0x0103, 0x0104, 0x0105),
    RED_AIR: 0x0106,
    
    BLUE_HERO: 0x0165,
    BLUE_ENGINEER: 0x0166,
    BLUE_INFANTRY: (0x0167, 0x0168, 0x0169),
    BLUE_AIR: 0x016A,
    REFREE_SERVER: 0x8080,
}

# CLIENT_ID_TO_NAME: 选手端十六进制 ID -> 名称
CLIENT_ID_TO_NAME: dict[int, str] = reverse(NAME_TO_CLIENT_ID)

ALLOWED_CLIENT_ID: list[int] = list(CLIENT_ID_TO_NAME.keys())

DOWNLINK_TOPICS: set[str] = {
    "GameStatus", "GlobalUnitStatus", "GlobalLogisticsStatus",
    "GlobalSpecialMechanism", "Event", "RobotInjuryStat",
    "RobotRespawnStatus", "RobotStaticStatus", "RobotDynamicStatus",
    "RobotModuleStatus", "RobotPosition", "Buff", "PenaltyInfo",
    "RobotPathPlanInfo", "RadarInfoToClient", 
    "TechCoreMotionStateSync", "RobotPerformanceSelectionSync",
    "DeployModeStatusSync", "RuneStatusSync", "SentryStatusSync",
    "DartSelectTargetStatusSync", "SentryCtrlResult", "AirSupportStatusSync",
    "CustomByteBlock"
}

UPLINK_TOPICS: set[str] = {
    "CommonCommand", "RobotPerformanceSelectionCommand",
    "HeroDeployModeEventCommand", "RuneActivateCommand", "DartCommand","AirsupportCommand",
    "MapClickInfoNotify", "AssemblyCommand", "SentryCtrlCommand",

    "KeyboardMouseControl", "CustomControl"
}

ALL_TOPICS: set[str] = DOWNLINK_TOPICS.union(UPLINK_TOPICS)

def get_cli_id_by_name(name: str) -> int | tuple[int, ...]:
    """根据机器人名称获取对应的 MQTT client_id。"""
    if name not in NAME_TO_CLIENT_ID:
        raise ValueError(f"未知的机器人名称: {name}")
    return NAME_TO_CLIENT_ID[name]

def get_id_by_name(name: str):
    """根据机器人名称获取对应的数字 ID。"""
    if name not in NAME_TO_ID:
        raise ValueError(f"未知的机器人名称: {name}")
    return NAME_TO_ID[name]

if __name__ == "__main__":
    # 英雄测试（普通兵种）
    player = PlayerTypes(Sides.BLUE, RobotTypes.HERO)
    print(player)
    id_1 = player.get_cli_id()
    print(id_1, id_1 == 0x0165)
    # 步兵测试(红2步兵，client_id：0x0104)(索引从1开始)
    player = PlayerTypes(Sides.RED, RobotTypes.INFANTRY, Infantry_Select=2)
    print(player)
    id_2 = player.get_cli_id()
    print(id_2, id_2 == 0x0104)


if __name__ == "__main__":
    # 测试 ID 和名称的映射关系
    for name, id_ in NAME_TO_ID.items():
        print(f"{name} -> {id_}")
    for id_, name in ID_TO_NAME.items():
        print(f"{id_} -> {name}")
    for name, client_id in NAME_TO_CLIENT_ID.items():
        print(f"{name} -> {client_id}")
    for client_id, name in CLIENT_ID_TO_NAME.items():
        print(f"{client_id} -> {name}")