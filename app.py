import cv2
import time
import threading
from typing import Optional
from flask import Flask, Response, render_template

import config
import models.consts as consts
from tools.rm_logger import RMColorLogger
from service.core_service import CoreService
from tools.rm_command import Cli, Layer, Option

FPS = 30

logger = RMColorLogger("MainApp")

app = Flask(__name__)
# service: Optional[CoreService] = None

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
        # # 每次调用 generate 都创建新的 handler
        # handler = NormalImgSource(host="127.0.0.1", port=12346)
        # handler.start()
        
        # try:
        #     while True:
        #         frame = handler.get_frame()
        #         if frame is not None:
        #             ret, buffer = cv2.imencode('.jpg', frame)
        #             if ret:
        #                 yield (b'--frame\r\n'
        #                        b'Content-Type: image/jpeg\r\n\r\n' + 
        #                        buffer.tobytes() + b'\r\n')
        #         time.sleep(1 / FPS)
        #         logger.debug("成功获取并编码一帧视频数据，正在发送...")
        # finally:
        #     # 确保连接关闭时清理资源
        #     handler.stop()
        #     logger.info("视频流生成器已停止，UDP接收线程已关闭")
    
    return Response(generate(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return render_template('index.html')


def run_flask():
        # Flask 必须跑在主线程；关闭 reloader，避免开发重载导致 service 重复初始化。
    app.run(host='127.0.0.1', port=5000, use_reloader=False)


def start_service():
    global service

    service = CoreService(
        side=consts.Sides.RED,
        robot=consts.RobotTypes.INFANTRY,
        infantry_select=2,
        mqtt_host="127.0.0.1",
        port_mqtt=3333,
        udp_bind_host="0.0.0.0",
        port_udp=3334,
        test_config=consts.TestConfig(if_test=True, if_mqtt_source=True)
    )
    service.run(blocking=False)

    
if __name__ == '__main__':
    # [部署约束]
    # 官方协议下 MQTT 服务端固定为 192.168.12.1:3333，
    # 而 UDP 图传接收必须绑定本机地址（建议 0.0.0.0 监听所有网卡）。
    # 两者语义不同，禁止复用为同一个 host 参数。
    start_service()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    while True:
        time.sleep(1)

    """
     - 设计命令类（q=返回）
     - 1. 查询服务状态
       - 1. 查询服务是否在运行（服务包含：flask服务；mqtt服务；udp接收服务；mqtt图传解码线程服务；图传源动态切换服务）
       - 2. 查询当前图传数据源（MQTT/UDP）
       - 3. 状态机（3种：所有状态（dict），某个主题的状态，某个主题的属性的值）
     - 2. 日志
       - 1. 命令行模式（默认）+ 获取日志buffer的内容
       - 2. 实时模式，按q返回命令行模式
       - 3. 日志级别设置（默认INFO，可简写）
     - 3. 测试
       - 1. 启动测试
         - 1. 启用mqtt图传源测试（修改test_config即可）
         - 2. 启用udp图传源测试
       - 2. 禁用测试
     - 4. 其他功能
       - 1. 动态修改客户端的id（需要重启MQTT连接才能生效）
    """
    def set_mqtt_source():
        service.test_config.if_test = True
        service.test_config.if_mqtt_source = True

    def set_udp_source():
        service.test_config.if_test = True
        service.test_config.if_udp_source = True

    def disable_test():
        service.test_config.if_test = False
        service.test_config.if_mqtt_source = False
        service.test_config.if_udp_source = False

    # root_layer = Layer("查询服务状态|日志|测试", "输入对应数字进入子菜单，输入?查看帮助信息，输入q返回上层菜单",
    #                     Layer("查询服务是否在运行|查询当前图传数据源|状态机查询", "查询核心服务的基本运行状态，查询当前使用的图传数据源（MQTT/UDP），状态机查询，支持查询所有状态、某个主题的状态、某个主题的属性值",
    #                          Option("查询服务是否在运行", "查询核心服务的基本运行状态", service.print_if_alive),
    #                          Option("查询当前图传数据源", "查询当前使用的图传数据源（MQTT/UDP）", service.print_current_source),
    #                          Layer("查询所有|查询主题|查询主题属性", "状态机查询，支持查询所有状态、某个主题的状态、某个主题的属性值",
    #                               Option("查询所有状态", "获取所有状态数据，便于调试使用", service.print_all_topics),
    #                               Option("查询某个主题的状态", "输入主题名称，获取该主题的状态数据", service.print_topic),
    #                               Option("查询某个主题的属性值", "输入主题名称和属性名称，获取该属性的值", service.print_topic_key)
    #                               )
    #                          ),
    #                     Layer("获取日志|日志级别设置", "日志功能，支持命令行模式和实时模式，并且可以设置日志级别",
    #                         Option("获取日志", "获取日志buffer的内容", logger.get_buffered_logs),
    #                         # Option("实时模式", "实时输出日志，按q返回命令行模式"),
    #                         Layer("DEBUG|INFO|WARNING|ERROR|CRITICAL", "设置日志级别，例如 DEBUG、INFO、WARNING、ERROR、CRITICAL",
    #                                 Option("DEBUG", "设置日志级别为 DEBUG", logger.set_level, "DEBUG"),
    #                                 Option("INFO", "设置日志级别为 INFO", logger.set_level, "INFO"),
    #                                 Option("WARNING", "设置日志级别为 WARNING", logger.set_level, "WARNING"),
    #                                 Option("ERROR", "设置日志级别为 ERROR", logger.set_level, "ERROR"),
    #                                 Option("CRITICAL", "设置日志级别为 CRITICAL", logger.set_level, "CRITICAL")
    #                               )
    #                          ),
    #                     Layer("启用测试|禁用测试", "测试功能，支持启用MQTT图传源测试和UDP图传源测试",
    #                           Layer("启动mqtt测试|启动udp测试", "启用mqtt图传源测试|启用udp图传源测试", 
    #                                 Option("启用mqtt图传源测试", "启用mqtt图传源测试（修改test_config即可）", set_mqtt_source),
    #                                 Option("启用udp图传源测试", "启用udp图传源测试（修改test_config即可）", set_udp_source),
    #                                 ),
    #                           Option("禁用测试", "禁用mqtt与udp图传测试", disable_test) 
    #                           ),
    #                     # Layer("其他功能", "目前包含：修改客户端ID", 
    #                     #       Option("动态修改客户端ID", "输入新的客户端ID，修改后需要重启MQTT连接", )
    #                     #       )
    #                    )
    # cli = Cli(root_layer)
    # cli.start_loop()
    # while True:
    #     time.sleep(1)