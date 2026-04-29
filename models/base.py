"""
dataclass消息基类
所有消息类的基类，提供标准化的消息结构

一个消息基类，应该包含什么？

"""

# models/base.py
import json
from dataclasses import fields, is_dataclass
from typing import TypeVar, Type, Any, ClassVar

from google.protobuf.message import Message
from google.protobuf.json_format import ParseDict, MessageToDict


T = TypeVar('T', bound='BaseMessage')


class BaseMessage:
    """消息基类 - 内部使用 protobuf 作为真实存储"""

    _INTERNAL_ATTRS: ClassVar[set[str]] = {
        'PB_CLASS', '_pb', '_ensure_pb', '_field_names', 'create_from_dict',
        'create_from_protobuf', 'create_from_json', 'from_dict', 'to_dict',
        'from_protobuf', 'to_protobuf', 'from_json', 'to_json', 'topic',
        '__dict__', '__class__', '__repr__', '__post_init__'
    }
    
    PB_CLASS: ClassVar[Type[Message] | None] = None

    def __init__(self, *args: Any, **kwargs: Any):
        """支持位置参数、关键字参数两种初始化方式。"""
        self._ensure_pb()

        if not args and not kwargs:
            return

        field_names = self._field_names()
        if len(args) > len(field_names):
            raise TypeError(
                f"{type(self).__name__} 期望最多 {len(field_names)} 个位置参数，实际得到 {len(args)} 个"
            )

        payload: dict[str, Any] = {}
        for idx, value in enumerate(args):
            payload[field_names[idx]] = value
        payload.update(kwargs)
        self.from_dict(payload)

    def __post_init__(self):
        """兼容 dataclass 子类：确保 protobuf 存储在初始化后可用。"""
        self._ensure_pb()

    @classmethod
    def _field_names(cls) -> list[str]:
        if is_dataclass(cls):
            return [f.name for f in fields(cls) if not f.name.startswith('_')]

        annotations = getattr(cls, '__annotations__', {})
        names: list[str] = []
        for name in annotations:
            if name.startswith('_') or name == 'PB_CLASS':
                continue
            names.append(name)
        return names

    @classmethod
    def create_from_dict(cls: Type[T], data: dict[str, Any]) -> T:
        msg = cls()
        msg.from_dict(data)
        return msg

    @classmethod
    def create_from_protobuf(cls: Type[T], data: bytes) -> T:
        msg = cls()
        msg.from_protobuf(data)
        return msg

    @classmethod
    def create_from_json(cls: Type[T], json_str: str) -> T:
        msg = cls()
        msg.from_json(json_str)
        return msg


    def _ensure_pb(self) -> Message | None:
        """懒初始化 protobuf 存储，兼容 dataclass 未调用基类 __init__ 的场景。"""
        if '_pb' not in self.__dict__:
            super().__setattr__('_pb', self.PB_CLASS() if self.PB_CLASS else None)
        return self.__dict__.get('_pb')
    
    def __getattribute__(self, name: str) -> Any:
        """优先从 protobuf 读取字段，避免 dataclass 默认值遮蔽真实值。"""
        if name.startswith('_') or name in BaseMessage._INTERNAL_ATTRS:
            return super().__getattribute__(name)

        pb = super().__getattribute__('_ensure_pb')()
        if pb and hasattr(pb, name):
            return getattr(pb, name)
        return super().__getattribute__(name)
    
    def __setattr__(self, name: str, value: Any) -> None:
        """代理属性设置到 protobuf 对象"""
        if name == '_pb' or name.startswith('_'):
            super().__setattr__(name, value)
        else:
            pb = self._ensure_pb()
            if pb and hasattr(pb, name):
                try:
                    setattr(pb, name, value)
                except (AttributeError, TypeError, ValueError):
                    # repeated / map 字段不支持直接整体赋值，改为容器就地更新。
                    container = getattr(pb, name)

                    if isinstance(value, (list, tuple)) and hasattr(container, 'clear'):
                        container.clear()
                        for item in value:
                            if isinstance(item, BaseMessage):
                                item = item._ensure_pb()

                            if isinstance(item, dict) and hasattr(container, 'add'):
                                ParseDict(item, container.add())
                            elif hasattr(container, 'append'):
                                container.append(item)
                            elif hasattr(container, 'extend'):
                                container.extend([item])
                            else:
                                raise
                        return

                    if isinstance(value, dict) and hasattr(container, 'clear') and hasattr(container, 'update'):
                        container.clear()
                        container.update(value)
                        return

                    raise
            else:
                super().__setattr__(name, value)

    def __repr__(self) -> str:
        return self.to_json()
    
    def topic(self) -> str:
        """默认主题为 protobuf 消息类名，子类可覆盖"""
        if self.PB_CLASS is None:
            return type(self).__name__
        return self.PB_CLASS.DESCRIPTOR.name

    def from_dict(self, data: dict[str, Any]) -> 'BaseMessage':
        """从字典创建消息"""
        pb = self._ensure_pb()
        if pb:
            pb.Clear()
            ParseDict(data, pb)
        return self
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        pb = self._ensure_pb()
        if pb:
            return MessageToDict(pb, preserving_proto_field_name=True)
        return {}
    
    def from_protobuf(self, data: bytes) -> 'BaseMessage':
        """从 protobuf 字节流创建消息"""
        pb = self._ensure_pb()
        if pb:
            pb.ParseFromString(data)
        return self
    
    def to_protobuf(self) -> bytes:
        """转换为 protobuf 字节流"""
        pb = self._ensure_pb()
        if pb:
            return pb.SerializeToString()
        return b''

    def from_json(self, json_str: str) -> 'BaseMessage':
        """从 JSON 字符串创建消息"""
        data = json.loads(json_str)
        return self.from_dict(data)
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), default=str)


if __name__ == "__main__":
    pass  # 这里可以指定一个 protobuf Message 类
