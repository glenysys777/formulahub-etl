"""Component registry."""

from __future__ import annotations

from typing import Type

from formulaetl.sdk.base import BaseComponent


_REGISTRY: dict[str, Type[BaseComponent]] = {}


def register(cls: Type[BaseComponent]) -> Type[BaseComponent]:
    """Decorator to register a component class by its component_type."""
    key = cls.component_type
    if not key or key == "base":
        raise ValueError(f"Invalid component_type on {cls}")
    _REGISTRY[key] = cls
    return cls


def get_component(component_type: str) -> Type[BaseComponent]:
    if component_type not in _REGISTRY:
        # Lazy-load components package on first miss
        import formulaetl.components  # noqa: F401

    if component_type not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown component type '{component_type}'. Known: {known}")
    return _REGISTRY[component_type]


def create_component(component_type: str, config: dict | None = None) -> BaseComponent:
    cls = get_component(component_type)
    return cls(config or {})


def list_components() -> list[dict]:
    import formulaetl.components  # noqa: F401

    return [
        {
            "type": cls.component_type,
            "display_name": cls.display_name,
            "category": cls.category,
            "config_schema": cls.config_schema,
            "parameters": cls.get_parameters(),
        }
        for cls in _REGISTRY.values()
    ]
