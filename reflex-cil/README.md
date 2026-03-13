# reflex-cil

基于 `自定义客户端布局-native.html` 的 Reflex 版本布局示例。
下半部分已按 `Docs/通信协议.pdf` p.47-结尾的 MQTT + Protobuf 协议接入。

## 快速启动

1. 进入目录：
   ```powershell
   cd CustomClient\PIONEER-client\reflex-cil
   ```
2. 安装依赖：
   ```powershell
   pip install -r requirements.txt
   ```
3. 运行项目：
   ```powershell
   reflex run
   ```

## 已实现内容

- 左上：视频播放区域占位
- 右上：地图区域占位
- 左下：
  - `发射机构选项`、`飞镖目标`、`底盘选项` 为下拉框
  - 其余控制项均为按钮
- 下半部分协议接入：
   - 订阅：`GameStatus`、`GlobalUnitStatus`、`GlobalLogisticsStatus`、`DeployModeStatusSync`、`DartSelectTargetStatusSync`、`RobotRespawnStatus`、`RobotDynamicStatus`、`RobotStaticStatus`
  - 发送：`CommonCommand`、`RobotPerformanceSelectionCommand`、`HeroDeployModeEventCommand`、`RuneActivateCommand`、`DartCommand`
   - UI 的时间、经济、科技、伤害、基地/前哨血条、部署状态、飞镖目标/灯态、复活与远程补给按钮可用性将按协议下行实时刷新
  - 左上图传与右上小地图仍为占位（按当前需求暂不改动）

## 协议联调建议

1. 启动 `mqtt-broker` 服务（端口 `3333`）：
   ```powershell
   cd ..\mqtt-broker
   python broker_service.py --host 0.0.0.0 --port 3333
   ```
2. 启动 `rm-server` 服务（Broker 的订阅者/发布者）：
   ```powershell
   cd ..\rm-server
   python rm_service.py --host 127.0.0.1 --port 3333
   ```
3. 启动 Reflex 页面：
   ```powershell
   cd ..\reflex-cil
   reflex run
   ```
