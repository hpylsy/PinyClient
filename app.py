from flask import Flask, Response, render_template
import cv2
import time
from typing import Optional

from tools.rm_logger import RMColorLogger
from service.core_service import CoreService
import models.consts as consts

FPS = 30

logger = RMColorLogger("MainApp")

app = Flask(__name__)
service: Optional[CoreService] = None

@app.route('/video_feed')
def video_feed():
    def generate():
        try:
            while True:
                if service is None:
                    logger.error("CoreService 尚未启动，无法获取视频帧")
                    break
                frame = service.get_cur_handler().get_frame()
                logger.debug("尝试获取视频帧...")
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

if __name__ == '__main__':
    # [部署约束]
    # 官方协议下 MQTT 服务端固定为 192.168.12.1:3333，
    # 而 UDP 图传接收必须绑定本机地址（建议 0.0.0.0 监听所有网卡）。
    # 两者语义不同，禁止复用为同一个 host 参数。
    service = CoreService(
        side=consts.Sides.RED,
        robot=consts.RobotTypes.INFANTRY,
        infantry_select=2,
        mqtt_host="192.168.12.1", 
        udp_bind_host="0.0.0.0",
    )
    service.run(blocking=False)
    try:
        # Flask 必须跑在主线程；关闭 reloader，避免开发重载导致 service 重复初始化。
        app.run(host='127.0.0.1', port=5000, use_reloader=False)
    finally:
        service.stop()
