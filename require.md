# 对客户端的要求
**"*"表示数据可变，否则数据固定**

说明：*: 表示可变; int\*：表示可变的整数; [1:4]\*说明从1~4中取值; (0\*, 1)\*说明从0，1中取值，默认1

## reflex-cil 左下端（操作区）

| 区域项 | 指令名 | 数据编号.数据 | 频率 | 注意 |
| :---- | :---- | :----------- | :-- |
| 17mm 按钮 | CommonCommand | 1.1; 2.int* | 触发式发送，最高10hz |
| 42mm 按钮 | CommonCommand | 1.2; 2.int* | 触发式发送，最高10hz |
| 复活 按钮 | CommonCommand | 1.3; 2.0 | 触发式发送，最高10hz |
| 金币复活 按钮 | CommonCommand | 1.4; 2.0 | 触发式发送，最高10hz |
| 远程补弹 按钮 | CommonCommand | 1.5; 2.int* | 触发式发送，最高10hz |
| 远程补血 按钮 | CommonCommand | 1.6; 2.int* | 触发式发送，最高10hz |
| 发射机构选项 下拉 | RobotPerformanceSelectionCommand | 1.[1:4]\* | 1Hz |
| 底盘选项 下拉 | RobotPerformanceSelectionCommand | 2.[1:4]\* | 1Hz |
| 开启部署/退出部署 按钮 | HeroDeployModeEventCommand | 1.mode(1=进入,0=退出) | 1Hz |
| 能量机关 按钮 | RuneActivateCommand | 1.activate(1) | 1Hz |
| 飞镖目标 下拉 + 开闸/发射 按钮 | DartCommand | 1.target_id*; 2.open*; 3.launch_confirm* | 1Hz | 先开闸再发射，开闸为2.1;3.0，发射为2.0;3.1 |

备注：左下包含若干空白占位格，仅用于布局，不对应协议指令。

## reflex-cil 右下端（状态区）

| 区域项 | 指令名 | 数据编号.参数 | 频率 | 注意事项 |
| :---- | :---- | :----------- | :-- |
| 剩余时间/总时间 | GameStatus | 6.stage_countdown_sec; 7.stage_elapsed_sec(总时间=二者计算) | 5Hz |
| 己方基地状态(血条) | GlobalUnitStatus | 1.base_health | 1Hz |
| 己方前哨状态(血条) | GlobalUnitStatus | 4.outpost_health | 1Hz |
| 敌方基地状态(血条) | GlobalUnitStatus | 6.enemy_base_health | 1Hz |
| 敌方前哨状态(血条) | GlobalUnitStatus | 9.enemy_outpost_health | 1Hz |
| 当前经济 | GlobalLogisticsStatus | 1.remaining_economy | 1Hz |
| 科技等级（当前实现显示位） | GlobalLogisticsStatus | 3.tech_level | 1Hz |
| 总伤害（己/敌） | GlobalUnitStatus | 13.total_damage_ally; 14.total_damage_enemy | 1Hz |
| 部署状态指示 | DeployModeStatusSync | 1.status | 1Hz | 监听1.status，若为0，则（部署的右边）显示红色，若为1，显示绿色 |
| 飞镖目标与开闸状态同步 | DartSelectTargetStatusSync | 2.open | 1Hz | 监听来自服务端的2.open，若open为0，则（飞镖目标右边的指示灯）显示红色，若open为1，显示橙黄色，open为2，显示绿色 |
| 复活按钮可用性同步 | RobotRespawnStatus | 4.can_free_respawn; 6.can_pay_for_respawn; 5.gold_cost_for_respawn | 1Hz | web中的复活改成免费复活 |
| 远程补给按钮可用性同步 | RobotDynamicStatus | 12.can_remote_heal; 13.can_remote_ammo | 10Hz |
| 发射机构/底盘选项回显 | RobotStaticStatus | 6.performance_system_shooter; 7.performance_system_chassis | 1Hz | 监听服务端的6，若与本地的发射机构性能体系不符的话，强制修改其为符合，若服务端发送非法数据，则跳过这个阶段 |

备注：协议连接状态文字（已连接/未连接）为本地桥接状态显示，不属于协议字段。