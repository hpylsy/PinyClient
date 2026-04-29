import cmd2
from typing import Callable, Any

class Cli:
    SEPARATOR = "-------------------------------------------------"
    
    def __init__(self, root_layer: 'Layer'):
        self.root_layer = root_layer
        self.current_layer = root_layer

    def _print_separator(self, with_leading_newline: bool = False):
        if with_leading_newline:
            print(f"\n{self.SEPARATOR}")
        else:
            print(self.SEPARATOR)

    def _print_invalid_input(self, user_input: str):
        content = user_input.strip()
        if not content:
            print()
        print(self.SEPARATOR)
        print(f"无效输入:{content}" if content else "无效输入:")

    def _handle_back(self):
        if self.current_layer == self.root_layer:
            print("已在根菜单，无法返回。")
        else:
            self.current_layer = self.current_layer.get_parent()

    def _handle_help(self, user_input: str):
        if user_input == "?":
            self._print_separator()
            print(f"本层说明: {self.current_layer.helps}")
            return

        # 例如：?1 -> 返回选项1的helps
        num_str = user_input[1:].strip()
        try:
            num = int(num_str)
            child = self.current_layer.get_child_by_num(num)
            self._print_separator()
            print(f"选项说明: {child.helps}")
        except (ValueError, IndexError):
            self._print_invalid_input(user_input)

    def _handle_select(self, user_input: str):
        try:
            num = int(user_input)
            child = self.current_layer.get_child_by_num(num)
            if isinstance(child, Option):
                self._print_separator()
                print(f"执行选项: {child.name}, 执行结果如下:")
                child.execute()
            elif isinstance(child, Layer):
                self.current_layer = child
        except (ValueError, IndexError):
            self._print_invalid_input(user_input)

    def start_loop(self):
        self._print_separator(with_leading_newline=True)
        while True:
            user_input = self.current_layer.print_description().strip()

            if user_input == 'q':
                self._handle_back()
            elif user_input.startswith("?"):
                self._handle_help(user_input)
            else:
                self._handle_select(user_input)

            self._print_separator()
            

class Layer:
    def __init__(self, options: str, helps: str = "", *children):
        self.name = "root"
        self.raw_description = options
        self.helps = helps
        self.description, line = self.generate_description(self.raw_description)
        self.parent = self
        self.children = list(children)
        assert len(line) == len(self.children), f"{self.name} 描述中的选项数量与子节点数量不匹配: {self.children} vs {line}"
        for child, name in zip(self.children, line):
            child.parent = self
            child.name = name.strip()
            if isinstance(child, Layer):
                child._refresh_description()

    def __repr__(self) -> str:
        return f"Layer(name={self.name}, children={len(self.children)})"

    def _refresh_description(self):
        self.description, _ = self.generate_description(self.raw_description)
        
    
    def generate_description(self, raw_description: str, prefix: str = "", suffix: str = "") -> tuple[str, list[str]]:
        lines = raw_description.split("|")
        result = ""
        if prefix:
            result += prefix + "\n"
        else:
            result += "请选择操作:\n"
        
        for idx, line in enumerate(lines, start=1):
            result += f"{idx}. {line.strip()}\n"
        result += "\n"

        if suffix:
            result += f"({self.name}) " + suffix
        else:
            result += f"({self.name}) 'q': 返回上一级菜单; '?'或'?+选项编号': 查看选项说明; Ctrl+D: 退出程序"
        return result, lines

    def get_parent(self) -> 'Layer':
        return self.parent

    def get_children_list(self) -> list:
        return self.children
    
    def print_description(self):
        self._refresh_description()
        print(self.description)
        return input("请输入: ")

    def get_child_by_num(self, num: int):
        idx = num - 1
        if 0 <= idx < len(self.children):
            return self.children[idx]
        else:
            raise IndexError("Invalid index for children")
    

class Option:
    def __init__(self, name: str, helps: str, callback: Callable[..., Any] = lambda: None, *args, **kwargs):
        self.name = name    
        self.helps = helps
        self.parent = None
        self.callback: Callable[..., Any] = callback
        self.args = args
        self.kwargs = kwargs

    def __repr__(self) -> str:
        return f"Option(name={self.name})"

    def print_description(self):
        print(self.helps)

    def execute(self):
        self.callback(*self.args, **self.kwargs)

if __name__ == "__main__":
    def print_hi():
        print("hi")
    
    def print_hello():
        print("hello")

    def print_bye():
        print("bye")

    # ROOT_DESC = \
    # "欢迎使用PIONEER客户端命令行工具！" + \
    # "请选择操作:\n" + \
    # "1. 查询服务状态\n" + \
    # "2. 日志\n" + \
    # "3. 测试\n" + \
    # "4. 其他功能\n"
    root_layer = Layer("查询服务状态|日志|测试|其他功能", "这是根菜单，包含四个选项：查询服务状态、日志、测试和其他功能",
                        Layer("hi|hello", "这是一个示例选项层，包含两个选项：hi和hello",
                            Option("option1", "print hi", print_hi), 
                            Option("option2", "print hello", print_hello)),
                        Layer("bye", "这是另一个示例选项层，包含一个选项：bye",
                            Option("option3", "print bye", print_bye)),
                        Layer("you", "这是另一个示例选项层，包含一个选项：you",
                            Option("option4", "print you", lambda: print("you"))),
                        Layer("other1|other2", "这是另一个示例选项层，包含一个选项：other",
                            Option("option5", "print other", lambda: print("other")),
                            Layer("other2", "这是other的子层，包含一个选项：other2",
                                Option("option6", "print other2", lambda: print("other2"))
                            )
                        )
    )
    cli = Cli(root_layer)
    cli.start_loop()
