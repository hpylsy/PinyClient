import argparse
import cv2
import json
import time
from typing import Optional
from flask import Flask, Response, render_template, stream_with_context

import config
import models.consts as consts
import tools.component.rm_components as comp
from tools.rm_logger import RMColorLogger
from service.core_service import CoreService
from tools.app_launcher import start_log_or_console
from tools.component.rm_component_base import BlockPosition, GridConfig
from tools.component.rm_component_manager import ComponentManager

FPS = 30

logger = RMColorLogger("MainApp")

app = Flask(__name__)
service: Optional[CoreService] = None
_component_manager = ComponentManager()


SIDE_CHOICES = {
    "red": consts.Sides.RED,
    "blue": consts.Sides.BLUE,
}

ROBOT_CHOICES = {
    "hero": consts.RobotTypes.HERO,
    "engineer": consts.RobotTypes.ENGINEER,
    "infantry": consts.RobotTypes.INFANTRY,
    "air": consts.RobotTypes.AIR,
    "sentry": consts.RobotTypes.SENTRY,
    "dart": consts.RobotTypes.DART,
    "radar": consts.RobotTypes.RADAR,
}


def build_test_config(video_source: str) -> consts.TestConfig:
    if video_source == "auto":
        return consts.TestConfig()
    if video_source == "mqtt":
        return consts.TestConfig(if_test=True, if_mqtt_source=True)
    if video_source == "udp":
        return consts.TestConfig(if_test=True, if_udp_source=True)
    return consts.TestConfig(if_test=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PinyClient 上位机 Web 客户端。默认使用真实上下位机连接。"
    )
    parser.add_argument("--side", choices=SIDE_CHOICES.keys(), default="red")
    parser.add_argument("--robot", choices=ROBOT_CHOICES.keys(), default="hero")
    parser.add_argument(
        "--infantry-select",
        type=int,
        default=0,
        help="仅 robot=infantry 时使用，取值 1/2/3。",
    )
    parser.add_argument(
        "--mqtt-host",
        default="192.168.12.1",
        help="选手端 MQTT broker 地址。",
    )
    parser.add_argument("--mqtt-port", type=int, default=3333)
    parser.add_argument(
        "--udp-bind-host",
        default="0.0.0.0",
        help="本机 UDP 图传监听地址；正常部署建议 0.0.0.0。",
    )
    parser.add_argument("--udp-port", type=int, default=3334)
    parser.add_argument(
        "--video-source",
        choices=("auto", "udp", "mqtt", "none"),
        default="auto",
        help=(
            "图传源策略。auto 为正式模式：英雄按状态自动切换，非英雄固定 UDP；"
            "udp/mqtt/none 为显式测试覆盖。"
        ),
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="启动交互命令行而不是普通日志模式。",
    )
    parser.add_argument("--debug", action="store_true", help="启用 Flask debug。")
    args = parser.parse_args()
    if args.robot == "infantry" and args.infantry_select not in (1, 2, 3):
        parser.error("--robot infantry 时 --infantry-select 必须是 1/2/3")
    return args


def build_component_manager() -> ComponentManager:
    manager = ComponentManager()
    manager.add_components(
        comp.GameStatusComponent(
            id="game_status",
            position=BlockPosition.TOP_RIGHT,
            grid=GridConfig(start=(0, 0), size=(2, 2)),
            template="components/game_status.html",
            name="比赛状态",
        ),
        comp.RobotDynamicStatusComponent(
            id="robot_dynamic",
            position=BlockPosition.BOTTOM_RIGHT,
            grid=GridConfig(start=(0, 0), size=(2, 2)),
            template="components/robot_dynamic.html",
            name="机器人实时状态",
        ),
        comp.GlobalUnitStatusComponent(
            id="global_unit",
            position=BlockPosition.BOTTOM_LEFT,
            grid=GridConfig(start=(0, 0), size=(2, 3)),
            template="components/global_unit.html",
            name="全局单位状态",
        ),
    )
    return manager


def render_component(component):
    context = component.render_context(service)
    return render_template(
        component.template,
        component=component,
        component_data=context,
        **context,
    )

@app.route('/video_feed')
def video_feed():
    def generate():
        try:
            while True:
                if service is None:
                    logger.error("CoreService 尚未启动，无法获取视频帧")
                    break
                frame = service.get_cur_handler().get_frame()
                if frame is not None:
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + 
                               buffer.tobytes() + b'\r\n')
                time.sleep(1 / FPS)
        except Exception as e:
            logger.error(f"视频流生成器发生错误: {e}")
    
    return Response(generate(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template(
        'index.html',
        grid_config=config.GridConfig(),
        components=_component_manager,
        service=service,
        render_component=render_component,
    )


@app.route('/api/components/events')
def component_events():
    @stream_with_context
    def generate():
        while True:
            payload = {
                "timestamp": time.time(),
                "components": _component_manager.serialize_all(service),
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            time.sleep(0.3)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

if __name__ == '__main__':
    # [部署约束]
    # 官方协议下 MQTT 服务端固定为 192.168.12.1:3333，
    # 而 UDP 图传接收必须绑定本机地址（建议 0.0.0.0 监听所有网卡）。
    # 两者语义不同，禁止复用为同一个 host 参数。
    args = parse_args()
    _component_manager = build_component_manager()

    service = CoreService(
        side=SIDE_CHOICES[args.side],
        robot=ROBOT_CHOICES[args.robot],
        infantry_select=args.infantry_select,
        mqtt_host=args.mqtt_host,
        port_mqtt=args.mqtt_port,
        udp_bind_host=args.udp_bind_host,
        port_udp=args.udp_port,
        test_config=build_test_config(args.video_source),
    )
    # grid_config = config.GridConfig(
    #     right_up=(4, 2),
    #     right_down=(2, 2),
    #     left_down=(2, 6),
    #     components={
    #         "right_up": ["ComponentA", "ComponentB"],
    #         "right_down": ["ComponentC"],
    #         "left_down": ["ComponentD", "ComponentE", "ComponentF"]
    #     }
    # )

    start_log_or_console(
        service, 
        app,
        logger, 
        start_log=not args.console,
        start_debug=args.debug,
    )
