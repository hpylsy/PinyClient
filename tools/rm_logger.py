import logging
import os
import sys
from collections import deque
from typing import List
sys.path.append("..")  # 添加项目根目录到sys.path，方便导入模块
from config import Config  # pyright: ignore[reportImplicitRelativeImport]

RECORD_LOG, LOG_DIR = Config.RECORD_LOG, Config.LOG_DIR

# ============================================================
# 彩色日志
# ============================================================

class CircularLogBuffer:
    """循环日志缓冲区"""
    
    def __init__(self, maxlen: int = 30):
        self.buffer = deque(maxlen=maxlen)
    
    def add(self, log: str):
        self.buffer.append(log)
    
    def get_all(self) -> List[str]:
        return list(self.buffer)
    
    def get_last(self, n: int) -> List[str]:
        return list(self.buffer)[-n:]

    def clear(self):
        self.buffer.clear()

class RMColorLogger:
    """彩色日志生成器, 支持分组配色方案; 在命令行使用$env:PIONEER_LOG_LEVEL = "DEBUG"命令 """

    # 基础色
    C: dict[str, str]= {
        "RESET":   "\033[0m",
        "BOLD":    "\033[1m",
        "DIM":     "\033[2m",
        "ITALIC":  "\033[3m",
        "UNDER":   "\033[4m",

        # 前景色
        "BLACK":   "\033[30m",
        "RED":     "\033[31m",
        "GREEN":   "\033[32m",
        "YELLOW":  "\033[33m",
        "BLUE":    "\033[34m",
        "MAGENTA": "\033[35m",
        "CYAN":    "\033[36m",
        "WHITE":   "\033[37m",

        # 亮色
        "BRIGHT_RED":     "\033[91m",
        "BRIGHT_GREEN":   "\033[92m",
        "BRIGHT_YELLOW":  "\033[93m",
        "BRIGHT_BLUE":    "\033[94m",
        "BRIGHT_MAGENTA": "\033[95m",
        "BRIGHT_CYAN":    "\033[96m",
        "GRAY":           "\033[90m",

        # 背景色
        "BG_RED":     "\033[41m",
        "BG_GREEN":   "\033[42m",
        "BG_YELLOW":  "\033[43m",
        "BG_BLUE":    "\033[44m",
        "BG_MAGENTA": "\033[45m",
        "BG_CYAN":    "\033[46m",
    }

    # 分组配色方案
    THEMES: dict[str, dict[str, str]]= {
        # DEBUG 组：柔和灰蓝
        "DEBUG": {
            "time":  f"{C['GRAY']}{C['DIM']}",
            "level": f"{C['GRAY']}",
            "name":  f"{C['GRAY']}{C['ITALIC']}",
            "file":  f"{C['GRAY']}{C['DIM']}",
            "msg":   f"{C['GRAY']}",
        },
        # INFO 组：清新蓝绿
        "INFO": {
            "time":  f"{C['BRIGHT_CYAN']}{C['BOLD']}",
            "level": f"{C['BRIGHT_BLUE']}{C['BOLD']}",
            "name":  f"{C['CYAN']}",
            "file":  f"{C['GRAY']}{C['ITALIC']}",
            "msg":   f"{C['WHITE']}",
        },
        # WARNING 组：活力黄橙
        "WARNING": {
            "time":  f"{C['BRIGHT_YELLOW']}{C['BOLD']}",
            "level": f"{C['YELLOW']}{C['BOLD']}",
            "name":  f"{C['BRIGHT_YELLOW']}",
            "file":  f"{C['YELLOW']}",
            "msg":   f"{C['BRIGHT_YELLOW']}",
        },
        # ERROR 组：醒目红紫
        "ERROR": {
            "time":  f"{C['BRIGHT_RED']}{C['BOLD']}",
            "level": f"{C['RED']}{C['BOLD']}{C['UNDER']}",
            "name":  f"{C['MAGENTA']}",
            "file":  f"{C['RED']}",
            "msg":   f"{C['BRIGHT_RED']}",
        },
        # CRITICAL 组：最强红白
        "CRITICAL": {
            "time":  f"{C['WHITE']}{C['BOLD']}{C['BG_RED']}",
            "level": f"{C['WHITE']}{C['BOLD']}{C['BG_RED']}",
            "name":  f"{C['BRIGHT_RED']}{C['BOLD']}{C['BG_RED']}",
            "file":  f"{C['WHITE']}{C['BOLD']}{C['BG_RED']}",
            "msg":   f"{C['WHITE']}{C['BOLD']}{C['BG_RED']}",
        },
    }

    class MultiColorFormatter(logging.Formatter):
        def format(self, record):
            # 先手动设置 asctime 属性
            if not hasattr(record, 'asctime'):
                # 创建时间字符串
                record.asctime = self.formatTime(record, self.datefmt)

            theme = RMColorLogger.THEMES.get(record.levelname, RMColorLogger.THEMES["INFO"])
            C = RMColorLogger.C

            # 时间：彩色
            asctime = f"{theme['time']}{record.asctime}{C['RESET']}"
            # 级别：彩色 + 加粗
            levelname = f"{theme['level']}{record.levelname:8s}{C['RESET']}"
            # 模块名：彩色
            name = f"{theme['name']}{record.name}{C['RESET']}"
            # 文件名和行号：彩色
            filename = f"{theme['file']}{record.filename}:{record.lineno}{C['RESET']}"
            # 消息：彩色
            message = f"{theme['msg']}{record.getMessage()}{C['RESET']}"

            # 重新组装
            return f"{asctime} | {levelname} | {name} | {filename} | {message}"

    def __init__(self, name: str = "pioneer"):
        self.name = name
        self._logger = logging.getLogger(name)
        self._buffer = CircularLogBuffer(maxlen=30)
        self._configure()

    def _configure(self):
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
        datefmt = "%H:%M:%S"
        level_str = os.environ.get("PIONEER_LOG_LEVEL", Config.LEVEL).upper()
        self._logger.setLevel(getattr(logging, level_str, logging.INFO))
        self._logger.handlers.clear()
        self._logger.propagate = False

        # 无论是否开启标准输出，都保留内存缓冲用于测试与最近日志读取。
        buffer_handler = self._create_buffer_handler(fmt=fmt, datefmt=datefmt)
        self._logger.addHandler(buffer_handler)

        if Config.IF_LOG:
            # 流处理 
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            # 格式：[时间] | 级别 | 模块名 | 文件名:行号 | 消息
            handler.setFormatter(self.MultiColorFormatter(fmt, datefmt=datefmt))
            self._logger.addHandler(handler)
            
            # 文件处理
            if RECORD_LOG:
                import time
                log_name = f"{self.name}_{time.strftime('%Y_%m_%d')}.log"
                log_path = os.path.join(LOG_DIR, log_name)
                if not os.path.exists(os.path.dirname(log_path)):
                    os.makedirs(os.path.dirname(log_path))

                file_handler = logging.FileHandler(log_path, encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(self.MultiColorFormatter(fmt, datefmt=datefmt))
                self._logger.addHandler(file_handler)

    def _create_buffer_handler(self, fmt: str, datefmt: str):
        """创建用于缓冲的handler"""
        class BufferHandler(logging.Handler):
            def __init__(self, buffer):
                super().__init__()
                self.buffer = buffer
                self.setFormatter(RMColorLogger.MultiColorFormatter(fmt, datefmt=datefmt))
            
            def emit(self, record):
                self.buffer.add(self.format(record))
        
        return BufferHandler(self._buffer)

    def debug(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._logger.critical(msg, *args, **kwargs)

    def set_level(self, level_str: str):
        self._logger.setLevel(getattr(logging, level_str.upper(), logging.INFO))
        self.info(f"日志级别已设置为 {level_str.upper()}")

    def get_buffered_logs(self) -> List[str]:
        """获取当前缓冲区中的日志消息，返回一个列表并清空缓冲区。"""
        logs = self._buffer.get_all()
        self._buffer.clear()
        return logs

    def print_buffered_logs(self):
        """打印当前缓冲区中的日志消息，并清空缓冲区。"""
        logs = self.get_buffered_logs()
        for log in logs:
            print(log)

    def get_recent_logs(self, n: int) -> List[str]:
        """获取最近n条日志"""
        return self._buffer.get_last(n)

    def print_recent_logs(self, n: int):
        """打印最近n条日志"""
        logs = self.get_recent_logs(n)
        for log in logs:
            print(log)

if __name__ == "__main__":

    logger = RMColorLogger("test")
    logger.info("test")
    logger.debug("test")
    logger.warning("test")
    logger.error("test")
    logger.critical("test")
    # print(logger.get_buffered_logs())
    for log in logger.get_recent_logs(5):
        print(log)