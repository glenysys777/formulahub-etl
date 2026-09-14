"""Component SDK: BaseComponent contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from formulaetl.sdk.capabilities import LEGACY, ComponentCapabilities
from formulaetl.sdk.context import RunContext, ComponentResult
from formulaetl.sdk.params import resolve_parameters


class BaseComponent(ABC):
    """All FormulaETL components implement this contract.

    Subclasses declare ``component_type``, optional ``config_schema``
    (JSON-schema-like dict for docs/compat), ``parameters`` (UI param-first
    schema), ``capabilities`` (planner feed mode), and implement ``run``.

    Default capabilities are legacy: blocking ``list[dict]`` materialization.
    The runner still calls ``run(ctx, rows)``; DatasetHandle is adapted at
    the engine boundary.
    """

    component_type: ClassVar[str] = "base"
    display_name: ClassVar[str] = "Base"
    category: ClassVar[str] = "misc"
    config_schema: ClassVar[dict[str, Any]] = {}
    # Param-first UI schema: [{label, key, type, required, default, help, options?}]
    parameters: ClassVar[list[dict[str, Any]]] = []
    capabilities: ClassVar[ComponentCapabilities] = LEGACY

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @classmethod
    def get_parameters(cls) -> list[dict[str, Any]]:
        """Return normalized UI parameter definitions."""
        return resolve_parameters(cls.parameters, cls.config_schema)

    def get_capabilities(self) -> ComponentCapabilities:
        """Instance capabilities (planner). Override when config changes the mode."""
        return self.capabilities

    def validate_config(self) -> None:
        """Raise ValueError if required config keys are missing."""
        params = self.get_parameters()
        if params:
            missing = [
                p["key"]
                for p in params
                if p.get("required")
                and (p["key"] not in self.config or self.config[p["key"]] in (None, "", []))
            ]
        else:
            required = self.config_schema.get("required", [])
            missing = [k for k in required if k not in self.config or self.config[k] in (None, "")]
        if missing:
            raise ValueError(
                f"{self.component_type}: missing required config: {', '.join(missing)}"
            )

    @abstractmethod
    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        """Execute the component.

        Sources typically ignore ``rows`` and produce output.
        Transforms take ``rows`` and return transformed rows.
        Destinations consume ``rows`` and may return them unchanged.
        """

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} type={self.component_type}>"
