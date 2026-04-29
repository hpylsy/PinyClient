from collections import OrderedDict

try:
    from .rm_component_base import Component, BlockPosition
except ImportError:
    from rm_component_base import Component, BlockPosition


class ComponentManager:
    def __init__(self):
        self._components: OrderedDict[str, Component] = OrderedDict()

    def add_components(self, *components: Component) -> None:
        for component in components:
            self._validate_component(component)
            self._components[component.id] = component

    def by_position(self, position: BlockPosition) -> list[Component]:
        return [
            component
            for component in self._components.values()
            if component.position == position
        ]

    @property
    def right_up(self) -> list[Component]:
        return self.by_position(BlockPosition.TOP_RIGHT)

    @property
    def right_down(self) -> list[Component]:
        return self.by_position(BlockPosition.BOTTOM_RIGHT)

    @property
    def left_down(self) -> list[Component]:
        return self.by_position(BlockPosition.BOTTOM_LEFT)

    def serialize_all(self, service) -> dict[str, dict]:
        return {
            component.id: component.serialize(service)
            for component in self._components.values()
        }

    def _validate_component(self, component: Component) -> None:
        if not isinstance(component, Component):
            raise TypeError(f"组件必须继承 Component: {component!r}")
        if component.id in self._components:
            raise ValueError(f"组件 id 重复: {component.id}")
        component.grid.validate()


if __name__ == "__main__":
    from rm_component_base import GridConfig

    manager = ComponentManager()
    component = Component(
        id="demo",
        name="Demo",
        position=BlockPosition.TOP_RIGHT,
        grid=GridConfig((0, 0), (1, 1)),
        template="components/demo.html",
    )
    manager.add_components(component)
    print("右上组件:", manager.right_up)
