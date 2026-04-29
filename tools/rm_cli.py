from typing import Optional

from models.message import TOPIC2MSG, get_message_class
from service.core_service import CoreService
from tools.rm_command import Cli, Layer, Option
from tools.rm_logger import RMColorLogger


def set_mqtt_source(service: CoreService, logger: Optional[RMColorLogger] = None):
	if service is None:
		if logger is not None:
			logger.error("CoreService 尚未启动，无法切换到 MQTT 图传源")
		return
	service.use_mqtt_source_for_test()


def set_udp_source(service: CoreService, logger: Optional[RMColorLogger] = None):
	if service is None:
		if logger is not None:
			logger.error("CoreService 尚未启动，无法切换到 UDP 图传源")
		return
	service.use_udp_source_for_test()


def disable_test(service: CoreService, logger: Optional[RMColorLogger] = None):
	if service is None:
		if logger is not None:
			logger.error("CoreService 尚未启动，无法修改测试模式")
		return
	service.disable_test_mode()


def show_buffered_logs():
	logs = RMColorLogger.get_global_recent_logs(30)
	if not logs:
		print("暂无日志（最近30条为空）")
		return
	for line in logs:
		print(line)


def set_global_log_level(level: str, logger: Optional[RMColorLogger] = None):
	RMColorLogger.set_global_level(level)
	if logger is not None:
		logger.info(f"日志级别已设置为 {level.upper()}")


def _print_topic_hints(cur_topics: list[str]):
	if not cur_topics:
		print("当前状态机尚无主题数据。")
		return
	print("当前可查询主题:")
	for i, topic in enumerate(cur_topics, start=1):
		print(f"{i}. {topic}")


def _select_index_or_name(options: list[str], prompt: str, target_name: str) -> Optional[str]:
	"""支持通过序号或名称进行选择。"""
	raw = input(prompt).strip()
	if not raw:
		print(f"{target_name}不能为空")
		return None

	if raw.isdigit():
		idx = int(raw)
		if 1 <= idx <= len(options):
			return options[idx - 1]
		print(f"{target_name}序号超出范围，请输入 1~{len(options)}")
		return None

	if raw in options:
		return raw

	print(f"未找到{target_name}: {raw}")
	return None


def query_topic_interactive(service: CoreService):
	"""交互式查询某个主题的完整状态。"""
	cur_topics = sorted(service.get_all().keys())
	_print_topic_hints(cur_topics)
	topic = _select_index_or_name(cur_topics, "请输入主题编号或名称: ", "主题")
	if topic is None:
		return

	data = service.get(topic)
	if not data:
		print(f"未找到主题: {topic}")
		return

	print(f"主题 {topic} 的当前状态:")
	print(data)


def query_topic_key_interactive(service: CoreService):
	"""交互式查询某个主题的某个属性值。"""
	cur_topics = sorted(service.get_all().keys())
	_print_topic_hints(cur_topics)
	topic = _select_index_or_name(cur_topics, "请输入主题编号或名称: ", "主题")
	if topic is None:
		return

	field_names: list[str] = []
	if topic in TOPIC2MSG:
		msg_cls = get_message_class(topic)
		field_names = msg_cls._field_names()

	if field_names:
		print("该主题可访问属性:")
		for i, field_name in enumerate(field_names, start=1):
			print(f"{i}. {field_name}")
		key = _select_index_or_name(field_names, "请输入属性编号或名称: ", "属性")
		if key is None:
			return
	else:
		print("未找到该主题的属性定义，将按输入字段直接查询。")
		key = input("请输入属性名: ").strip()
		if not key:
			print("属性名不能为空")
			return

	if field_names and key not in field_names:
		print(f"属性 {key} 不在该主题定义中")
		return

	value = service.get(topic, key)
	print(f"{topic}.{key} = {value}")


def start_cli(service: CoreService, logger: Optional[RMColorLogger] = None):
	root_layer = Layer(
		"查询|日志|测试",
		"输入对应数字进入子菜单，输入?查看帮助信息，输入q返回上层菜单",
		Layer(
			"查询服务状态|查询当前图传数据源|状态机查询",
			"查询核心服务的基本运行状态，查询当前使用的图传数据源（MQTT/UDP），状态机查询，支持查询所有状态、某个主题的状态、某个主题的属性值",
			Option("查询服务是否在运行", "查询核心服务的基本运行状态", service.print_if_alive),
			Option("查询当前图传数据源", "查询当前使用的图传数据源（MQTT/UDP）", service.print_current_source),
			Layer(
				"查询所有|查询某个主题|查询某个主题的属性值",
				"状态机查询，支持查询所有状态、某个主题的状态、某个主题的属性值",
				Option("查询所有状态", "获取所有状态数据，便于调试使用", service.print_all_topics),
				Option("查询某个主题的状态", "输入主题名称，获取该主题的状态数据", query_topic_interactive, service),
				Option("查询某个主题的属性值", "输入主题名称和属性名称，获取该属性的值", query_topic_key_interactive, service),
			),
		),
		Layer(
			"获取日志|日志级别设置",
			"日志功能，支持命令行模式和实时模式，并且可以设置日志级别",
			Option("获取日志", "获取日志buffer的内容", show_buffered_logs),
			Layer(
				"DEBUG|INFO|WARNING|ERROR|CRITICAL",
				"设置日志级别，例如 DEBUG、INFO、WARNING、ERROR、CRITICAL",
				Option("DEBUG", "设置日志级别为 DEBUG", set_global_log_level, "DEBUG", logger),
				Option("INFO", "设置日志级别为 INFO", set_global_log_level, "INFO", logger),
				Option("WARNING", "设置日志级别为 WARNING", set_global_log_level, "WARNING", logger),
				Option("ERROR", "设置日志级别为 ERROR", set_global_log_level, "ERROR", logger),
				Option("CRITICAL", "设置日志级别为 CRITICAL", set_global_log_level, "CRITICAL", logger),
			),
		),
		Layer(
			"启用测试|禁用测试",
			"测试功能，支持启用MQTT图传源测试和UDP图传源测试",
			Layer(
				"启动mqtt测试|启动udp测试",
				"启用mqtt图传源测试|启用udp图传源测试",
				Option("启用mqtt图传源测试", "启用mqtt图传源测试（修改test_config即可）", set_mqtt_source, service, logger),
				Option("启用udp图传源测试", "启用udp图传源测试（修改test_config即可）", set_udp_source, service, logger),
			),
			Option("禁用测试", "禁用mqtt与udp图传测试", disable_test, service, logger),
		),
	)

	cli = Cli(root_layer)
	cli.start_loop()
