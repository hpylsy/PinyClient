import asyncio
from typing import Any

import reflex as rx

from . import video_server as _video_server
_video_server.start()

from .protocol_bridge import (
    CHASSIS_OPTION_TO_ENUM,
    DART_TARGET_TO_ID,
    SHOOTER_OPTION_TO_ENUM,
    bridge,
)


class DashboardState(rx.State):
    launcher_option: str = "冷却优先"
    dart_target: str = "前哨"
    chassis_option: str = "血量优先"

    total_time: int = 420
    remaining_time: int = 420

    economy_now: int = 0
    economy_total: int = 0
    tech_level: int = 1
    our_damage: int = 0
    enemy_damage: int = 0
    our_base_hp: int = 100
    our_outpost_hp: int = 100
    enemy_base_hp: int = 100
    enemy_outpost_hp: int = 100
    deploy_enabled: bool = False
    can_respawn: bool = False
    can_pay_for_respawn: bool = False
    can_remote_ammo: bool = False
    can_remote_heal: bool = False
    gold_respawn_cost: int = 0
    dart_open_status: int = 0
    robot_level: int = 1
    current_exp: int = 0
    upgrade_exp: int = 0
    ammo_17_display: str = ""
    ammo_42_display: str = "1"

    server_launcher_option: str = ""
    server_chassis_option: str = ""
    server_dart_target: str = ""
    server_deploy_enabled: bool = False
    warning_message: str = ""
    _server_launcher_seen: bool = False
    _server_chassis_seen: bool = False
    _server_dart_seen: bool = False
    _server_deploy_seen: bool = False

    protocol_connected: bool = False
    protocol_status: str = "未连接协议服务"
    _sync_loop_started: bool = False

    @rx.event
    def init_data(self):
        self.protocol_status = bridge.connect()
        self.protocol_connected = bridge.is_connected

    def _update_sync_warning(self):
        warnings: list[str] = []
        if self._server_launcher_seen and self.server_launcher_option != self.launcher_option:
            warnings.append("发射机构性能体系")
        if self._server_chassis_seen and self.server_chassis_option != self.chassis_option:
            warnings.append("底盘性能体系")
        if self._server_dart_seen and self.server_dart_target != self.dart_target:
            warnings.append("飞镖目标")
        if self._server_deploy_seen and self.server_deploy_enabled != self.deploy_enabled:
            warnings.append("部署模式")

        if warnings:
            self.warning_message = "警告: " + "、".join(warnings) + " 的修改可能未同步"
        else:
            self.warning_message = ""

    @rx.event(background=True)
    async def sync_loop(self):
        if self._sync_loop_started:
            return

        async with self:
            self._sync_loop_started = True

        while True:
            snapshot = bridge.poll()
            if snapshot:
                try:
                    async with self:
                        self.remaining_time = snapshot.get("remaining_time", self.remaining_time)
                        self.total_time = snapshot.get("total_time", self.total_time)
                        self.economy_now = snapshot.get("economy_now", self.economy_now)
                        self.economy_total = snapshot.get("economy_total", self.economy_total)
                        self.tech_level = snapshot.get("tech_level", self.tech_level)
                        self.our_damage = snapshot.get("our_damage", self.our_damage)
                        self.enemy_damage = snapshot.get("enemy_damage", self.enemy_damage)
                        self.our_base_hp = snapshot.get("our_base_hp", self.our_base_hp)
                        self.our_outpost_hp = snapshot.get("our_outpost_hp", self.our_outpost_hp)
                        self.enemy_base_hp = snapshot.get("enemy_base_hp", self.enemy_base_hp)
                        self.enemy_outpost_hp = snapshot.get("enemy_outpost_hp", self.enemy_outpost_hp)
                        self.can_respawn = snapshot.get("can_respawn", self.can_respawn)
                        self.can_pay_for_respawn = snapshot.get("can_pay_for_respawn", self.can_pay_for_respawn)
                        self.can_remote_ammo = snapshot.get("can_remote_ammo", self.can_remote_ammo)
                        self.can_remote_heal = snapshot.get("can_remote_heal", self.can_remote_heal)
                        self.gold_respawn_cost = snapshot.get("gold_respawn_cost", self.gold_respawn_cost)
                        self.dart_open_status = snapshot.get("dart_open_status", self.dart_open_status)
                        self.robot_level = snapshot.get("robot_level", self.robot_level)
                        self.current_exp = snapshot.get("current_exp", self.current_exp)
                        self.upgrade_exp = snapshot.get("upgrade_exp", self.upgrade_exp)
                        if "launcher_option" in snapshot:
                            self.server_launcher_option = snapshot.get("launcher_option", "")
                            self._server_launcher_seen = True
                        if "chassis_option" in snapshot:
                            self.server_chassis_option = snapshot.get("chassis_option", "")
                            self._server_chassis_seen = True
                        if "dart_target" in snapshot:
                            self.server_dart_target = snapshot.get("dart_target", "")
                            self._server_dart_seen = True
                        if "deploy_enabled" in snapshot:
                            self.server_deploy_enabled = bool(snapshot.get("deploy_enabled"))
                            self._server_deploy_seen = True
                        self._update_sync_warning()
                        self.protocol_connected = bridge.is_connected
                except Exception:
                    # Browser tab refreshed/closed: stop this stale background loop.
                    break
            await asyncio.sleep(0.2)

        try:
            async with self:
                self._sync_loop_started = False
        except Exception:
            pass

    @rx.var
    def dart_indicator_class(self) -> str:
        if self.dart_open_status == 2:
            return "deploy-indicator dart-indicator dart-on"
        if self.dart_open_status == 1:
            return "deploy-indicator dart-indicator dart-opening"
        return "deploy-indicator dart-indicator dart-off"

    @rx.var
    def our_base_hp_width(self) -> str:
        return f"{self.our_base_hp}%"

    @rx.var
    def our_outpost_hp_width(self) -> str:
        return f"{self.our_outpost_hp}%"

    @rx.var
    def enemy_base_hp_width(self) -> str:
        return f"{self.enemy_base_hp}%"

    @rx.var
    def enemy_outpost_hp_width(self) -> str:
        return f"{self.enemy_outpost_hp}%"

    @rx.event
    def set_launcher_option(self, value: str):
        self.launcher_option = value
        bridge.send_robot_performance_selection(
            shooter=SHOOTER_OPTION_TO_ENUM.get(self.launcher_option, 1),
            chassis=CHASSIS_OPTION_TO_ENUM.get(self.chassis_option, 1),
            sentry_control=0,
        )
        self._update_sync_warning()

    @rx.event
    def set_dart_target(self, value: str):
        self.dart_target = value
        target_id = DART_TARGET_TO_ID.get(self.dart_target, 1)
        bridge.send_dart_command(target_id=target_id, open_gate=False, launch_confirm=False)
        self._update_sync_warning()

    @rx.event
    def set_chassis_option(self, value: str):
        self.chassis_option = value
        bridge.send_robot_performance_selection(
            shooter=SHOOTER_OPTION_TO_ENUM.get(self.launcher_option, 1),
            chassis=CHASSIS_OPTION_TO_ENUM.get(self.chassis_option, 1),
            sentry_control=0,
        )
        self._update_sync_warning()

    @rx.event
    def enable_deploy(self):
        self.deploy_enabled = True
        bridge.send_hero_deploy_mode(True)
        self._update_sync_warning()

    @rx.event
    def disable_deploy(self):
        self.deploy_enabled = False
        bridge.send_hero_deploy_mode(False)
        self._update_sync_warning()

    @rx.event
    def set_17mm_amount(self, value: str):
        digits = "".join(ch for ch in value if ch.isdigit())
        self.ammo_17_display = digits

    @rx.event
    def set_42mm_amount(self, value: str):
        digits = "".join(ch for ch in value if ch.isdigit())
        self.ammo_42_display = digits

    @rx.event
    def send_17mm(self):
        raw = int(self.ammo_17_display) if self.ammo_17_display else 0
        amount = raw if raw % 10 == 0 else round(raw / 10) * 10
        bridge.send_common_command(cmd_type=1, param=amount)

    @rx.event
    def send_42mm(self):
        amount = int(self.ammo_42_display) if self.ammo_42_display else 0
        bridge.send_common_command(cmd_type=2, param=amount)

    @rx.event
    def send_respawn(self):
        bridge.send_common_command(cmd_type=3, param=0)

    @rx.event
    def send_gold_respawn(self):
        bridge.send_common_command(cmd_type=4, param=0)

    @rx.event
    def send_remote_ammo(self):
        bridge.send_common_command(cmd_type=5, param=0)

    @rx.event
    def send_remote_heal(self):
        bridge.send_common_command(cmd_type=6, param=0)

    @rx.event
    def open_dart_gate(self):
        target_id = DART_TARGET_TO_ID.get(self.dart_target, 1)
        bridge.send_dart_command(target_id=target_id, open_gate=True, launch_confirm=False)

    @rx.event
    def launch_dart(self):
        target_id = DART_TARGET_TO_ID.get(self.dart_target, 1)
        bridge.send_dart_command(target_id=target_id, open_gate=True, launch_confirm=True)

    @rx.event
    def activate_rune(self):
        bridge.send_rune_activate()


def action_button(label: Any, on_click=None, disabled: Any = False) -> rx.Component:
    return rx.button(label, class_name="cell button-cell", on_click=on_click, disabled=disabled)


def ammo_action_cell(title: str, value: Any, on_change, on_click) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.input(
                value=value,
                on_change=on_change,
                class_name="ammo-input",
                placeholder="0",
            ),
            rx.button(title, class_name="ammo-send", on_click=on_click),
            spacing="0",
            class_name="ammo-cell-content",
        ),
        class_name="cell ammo-cell",
    )


def select_cell(
    placeholder: str,
    options: list[str],
    value: str,
    on_change,
) -> rx.Component:
    return rx.select(
        options,
        value=value,
        placeholder=placeholder,
        on_change=on_change,
        class_name=rx.cond(value == "", "cell select-cell select-placeholder", "cell select-cell"),
    )


def status_bar_item(label: str, value: Any, width: Any) -> rx.Component:
    return rx.box(
        rx.box(class_name="hp-fill", width=width),
        rx.hstack(
            rx.text(label),
            rx.text(value, "%"),
            class_name="hp-label",
        ),
        class_name="status-bar-item",
    )


def index() -> rx.Component:
    return rx.box(
        rx.el.link(rel="stylesheet", href="/styles.css"),
        rx.script(src="/video-player.js"),
        rx.grid(
            rx.box(
                rx.el.video(
                    id="pioneer-video",
                    auto_play=True,
                    muted=True,
                    plays_inline=True,
                    style={"width": "100%", "height": "100%", "display": "block", "objectFit": "contain"},
                ),
                class_name="panel top-video",
            ),
            rx.box(
                "小地图（上下布局）",
                rx.el.br(),
                "包含标点工具？",
                class_name="panel top-map",
            ),
            rx.box(
                rx.grid(
                    ammo_action_cell("17mm", DashboardState.ammo_17_display, DashboardState.set_17mm_amount, DashboardState.send_17mm),
                    ammo_action_cell("42mm", DashboardState.ammo_42_display, DashboardState.set_42mm_amount, DashboardState.send_42mm),
                    action_button("免费复活", on_click=DashboardState.send_respawn, disabled=~DashboardState.can_respawn),
                    action_button(
                        rx.vstack(
                            rx.text("金币复活"),
                            rx.text("(", DashboardState.gold_respawn_cost, ")", class_name="cost-text"),
                            spacing="0",
                        ),
                        on_click=DashboardState.send_gold_respawn,
                        disabled=~DashboardState.can_pay_for_respawn,
                    ),
                    action_button("远程补弹", on_click=DashboardState.send_remote_ammo, disabled=~DashboardState.can_remote_ammo),
                    action_button("远程补血", on_click=DashboardState.send_remote_heal, disabled=~DashboardState.can_remote_heal),
                    action_button("能量机关", on_click=DashboardState.activate_rune),
                    action_button(""),
                    action_button(""),
                    class_name="actions",
                ),
                rx.grid(
                    select_cell(
                        "发射机构选项",
                        ["冷却优先", "爆发优先", "英雄近战优先", "英雄远程优先"],
                        DashboardState.launcher_option,
                        DashboardState.set_launcher_option,
                    ),
                    select_cell(
                        "底盘选项",
                        ["血量优先", "功率优先", "英雄近战优先", "英雄远程优先"],
                        DashboardState.chassis_option,
                        DashboardState.set_chassis_option,
                    ),
                    action_button(""),
                    action_button(""),
                    class_name="dropdowns",
                ),
                rx.grid(
                    rx.box(
                        rx.hstack(
                            select_cell(
                                "飞镖目标",
                                ["前哨", "基地固定", "基地随机固定", "基地随机移动", "基地末端移动"],
                                DashboardState.dart_target,
                                DashboardState.set_dart_target,
                            ),
                            rx.box(class_name=DashboardState.dart_indicator_class),
                            class_name="dart-target-row",
                        ),
                        class_name="dart-select-cell",
                    ),
                    rx.grid(
                        action_button("开闸", on_click=DashboardState.open_dart_gate),
                        action_button("发射", on_click=DashboardState.launch_dart),
                        class_name="dart-second-row",
                    ),
                    action_button(""),
                    action_button(""),
                    class_name="dart",
                ),
                rx.grid(
                    rx.box(
                        rx.hstack(
                            rx.text("部署"),
                            rx.box(
                                class_name=rx.cond(
                                    DashboardState.deploy_enabled,
                                    "deploy-indicator deploy-on",
                                    "deploy-indicator deploy-off",
                                )
                            ),
                            class_name="deploy-status-row",
                        ),
                        class_name="cell deploy-status-cell",
                    ),
                    rx.grid(
                        action_button("开启", on_click=DashboardState.enable_deploy),
                        action_button("退出", on_click=DashboardState.disable_deploy),
                        class_name="control-second-row",
                    ),
                    action_button(""),
                    action_button(""),
                    class_name="control",
                ),
                class_name="panel bottom-left",
            ),
            rx.box(
                rx.grid(
                    rx.box(
                        rx.text(
                            rx.text.span("⏱ ", class_name="metric-icon", aria_label="time icon"),
                            rx.text.span(DashboardState.remaining_time),
                            " / ",
                            rx.text.span(DashboardState.total_time),
                        ),
                        class_name="left-info-top",
                    ),
                    rx.box(
                        status_bar_item("己方基地状态", DashboardState.our_base_hp, DashboardState.our_base_hp_width),
                        status_bar_item("己方前哨状态", DashboardState.our_outpost_hp, DashboardState.our_outpost_hp_width),
                        class_name="status-list status-list-half",
                        spacing="0",
                        padding="0",
                    ),
                    rx.grid(
                        rx.box(
                            rx.text(
                                rx.text.span("🪙 ", class_name="metric-icon", aria_label="coin icon"),
                                rx.text.span(DashboardState.economy_now),
                            ),
                            class_name="cell",
                        ),
                        rx.box(
                            rx.text(
                                rx.text.span("🏢 ", class_name="metric-icon", aria_label="building icon"),
                                rx.text.span(DashboardState.tech_level),
                            ),
                            class_name="cell",
                        ),
                        rx.box(
                            rx.text(
                                rx.text.span("🔪 ", class_name="metric-icon", aria_label="knife icon"),
                                rx.text.span(DashboardState.our_damage),
                                " / ",
                                rx.text.span(DashboardState.enemy_damage),
                            ),
                            class_name="cell merged-damage",
                        ),
                        class_name="left-info-bottom",
                    ),
                    rx.box(
                        status_bar_item("敌方基地状态", DashboardState.enemy_base_hp, DashboardState.enemy_base_hp_width),
                        status_bar_item(
                            "敌方前哨状态",
                            DashboardState.enemy_outpost_hp,
                            DashboardState.enemy_outpost_hp_width,
                        ),
                        class_name="status-list status-list-half",
                        spacing="0",
                        padding="0",
                    ),
                    class_name="bottom-right",
                ),
                rx.box(
                    rx.text(
                        rx.cond(DashboardState.protocol_connected, "协议服务: 已连接", "协议服务: 未连接"),
                        " | ",
                        DashboardState.protocol_status,
                    ),
                    class_name="protocol-status",
                ),
                rx.cond(
                    DashboardState.warning_message != "",
                    rx.box(rx.text(DashboardState.warning_message), class_name="sync-warning"),
                    rx.box(),
                ),
                class_name="panel",
            ),
            class_name="dashboard",
        ),
        class_name="app-root",
    )


app = rx.App()
app.add_page(index, title="Reflex 自定义客户端布局", on_load=[DashboardState.init_data, DashboardState.sync_loop])
