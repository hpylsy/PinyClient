# PIONEER-client

## 重构后的目录架构

- `mqtt-broker/`：MQTT Broker 服务目录（仅 broker 功能）
- `rm-server/`：RM 服务端目录（broker 的订阅者 + 发布者）
- `reflex-cil/`：自定义客户端前端（Reflex），订阅下行并发布上行
- `protocol/`：共享 Protobuf 协议定义

## 启动顺序

1. 启动 Broker：

```powershell
cd CustomClient\PIONEER-client\mqtt-broker
.\setup_broker_env.ps1
.\run_broker.ps1
```

说明：`mqtt-broker` 使用独立 `.venv-broker`，避免与 `reflex-cil` 的 `click` 依赖冲突。

2. 启动 RM 服务：

```powershell
cd CustomClient\PIONEER-client\rm-server
pip install -r requirements.txt
python rm_service.py --host 127.0.0.1 --port 3333
```

3. 启动 Reflex 客户端：

```powershell
cd CustomClient\PIONEER-client\reflex-cil
pip install -r requirements.txt
reflex run
```

## 重构经验

- Broker 与 Reflex 使用独立环境：
	- `mqtt-broker` 使用 `.venv-broker`
	- Reflex/RM 使用主 `.venv`
	- 解决 `amqtt/typer` 与 `reflex` 的 `click` 版本冲突。
- paho-mqtt 回调必须兼容 v1/v2：
	- 客户端构造优先 `CallbackAPIVersion.VERSION2`
	- 回调签名使用 `properties=None` 兜底。
- 状态发布采用固定频率：
	- 时间与常规状态分频发布，避免 UI 抖动与状态覆盖。
- 前端按钮可用性由协议状态驱动：
	- 复活类看 `RobotRespawnStatus`
	- 远程补给看 `RobotDynamicStatus`
	- 飞镖灯态看 `DartSelectTargetStatusSync.open`。
