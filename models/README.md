# models 目录说明

本目录是协议模型层，负责三件事：
1. 维护比赛协议对应的数据结构。
2. 负责 protobuf <-> Python 对象 <-> dict/json 的互转。
3. 提供 topic 到消息类的统一映射，给 MQTT 层做动态解析。

## 目录结构

- `base.py`: 通用消息基类 `BaseMessage`。
- `message.py`: 全部消息枚举与 dataclass 模型，以及 `TOPIC2MSG` 映射。
- `consts.py`: 客户端 ID、机器人/阵营枚举、上下行 topic 集合。
- `protocol/`: `.proto` 与生成的 `messages_pb2.py`。
- `test_protocol.py`: 协议联调测试脚本。

## 核心逻辑

### 1) BaseMessage 统一协议对象行为

`base.py` 的 `BaseMessage` 是所有消息类基类，核心设计是内部只存 protobuf 对象：

- `PB_CLASS` 指定对应 protobuf 消息类型。
- `_ensure_pb()` 懒初始化底层 protobuf 实例。
- `from_dict()/to_dict()` 基于 `ParseDict/MessageToDict`。
- `from_protobuf()/to_protobuf()` 负责二进制互转。
- `__getattribute__/__setattr__` 将字段读写代理到 protobuf 对象。

关键收益：
- 避免每个消息类重复写序列化逻辑。
- 保证网络层拿到的对象总能直接转 protobuf 发布。

### 2) message.py 集中维护协议模型

`message.py` 集中定义：

- 比赛状态相关枚举（如 `GameStage`、`DeployModeStatus`）。
- 全部协议 dataclass（如 `GameStatus`、`GlobalUnitStatus`、`CustomControl`）。
- 主题映射 `TOPIC2MSG: dict[str, type[BaseMessage]]`。

`TOPIC2MSG` 是 MQTT 接收端的关键入口：

- 收到 topic 后，通过映射找到消息类。
- `parser_cls().from_protobuf(payload)` 反序列化。

### 3) consts.py 管理业务常量与 topic 集合

`consts.py` 提供：

- 阵营/机器人枚举（`Sides`、`RobotTypes`）。
- `PlayerTypes.get_cli_id()`，根据红蓝方与兵种计算 client_id。
- `DOWNLINK_TOPICS`、`UPLINK_TOPICS`。

这部分被 `service/core_service.py` 直接用于：

- 初始化 MQTT client_id。
- 校验 publish topic 合法性。

## 典型数据流

### 下行（服务器 -> 客户端）

1. MQTT 收到 `topic + payload(bytes)`。
2. 用 `TOPIC2MSG[topic]` 找到消息类。
3. `from_protobuf(payload)` 得到模型对象。
4. 再由 service 层更新状态机或触发业务逻辑。

### 上行（客户端 -> 服务器）

1. 业务层构造 dict。
2. 模型类 `from_dict()` 转 protobuf 对象。
3. `to_protobuf()` 得到 bytes。
4. MQTT 按 topic 发布。

## 维护建议

1. 新增协议字段时，先更新 `.proto` 并重新生成 `messages_pb2.py`。
2. 再同步更新 `message.py` 对应 dataclass 与 `TOPIC2MSG`。
3. 最后检查 `consts.py` 的上下行 topic 是否需要新增。

