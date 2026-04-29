import logging
import threading
from typing import TYPE_CHECKING, Callable

import config
from tools.rm_logger import RMColorLogger
from .rm_cli import start_cli

if TYPE_CHECKING:
	from flask import Flask
	from service.core_service import CoreService


def run_flask(app: "Flask", start_log: bool = False, start_debug: bool = False):
	# Flask 关闭 reloader/debug，避免开发重载导致 service 重复初始化。
	# app.run(host="127.0.0.1", port=5000, use_reloader=start_log, debug=start_debug)
	app.run(host="127.0.0.1", port=5000, use_reloader=False, debug=start_debug)


def start_flask(app: "Flask", blocking: bool = True, start_log: bool = False, start_debug: bool = False):
	if blocking:
		run_flask(app, start_log, start_debug)
	else:
		flask_thread = threading.Thread(target=run_flask, args=(app, start_log, start_debug), daemon=True)
		flask_thread.start()


def configure_logging_modes(app: "Flask", start_log: bool):
	"""按启动模式切换日志策略。"""
	config.Config.RECORD_LOG = False
	config.Config.IF_LOG = start_log

	if start_log:
		app.logger.disabled = False
		logging.getLogger("werkzeug").disabled = False
	else:
		# app.run 的启动横幅不是走常规 logger，这里单独静默。
		try:
			import flask.cli
			flask.cli.show_server_banner = lambda *args, **kwargs: None
		except Exception:
			pass

		app.logger.disabled = True
		werkzeug_logger = logging.getLogger("werkzeug")
		werkzeug_logger.disabled = True
		werkzeug_logger.setLevel(logging.CRITICAL)

	RMColorLogger.reload_all_loggers()


def start_log_or_console(
	service: "CoreService",
	app: "Flask",
	logger: RMColorLogger,
	start_log: bool = True,
	start_debug: bool = False
):
	configure_logging_modes(app, start_log)

	if start_log:
		print("正在启动日志界面...")
	else:
		print("正在启动命令行服务（需要连接上MQTT broker才可进入界面，Ctrl+C退出）...")

	started = service.run(blocking=False)
	if not started:
		print("启动已取消，程序退出。")
		return

	if start_log:
		start_flask(app, blocking=True, start_log=True, start_debug=start_debug)
	else:
		start_flask(app, blocking=False, start_log=False, start_debug=start_debug)
		start_cli(service, logger)