"""Deterministic legacy model: what the parsers extract before any AI is involved."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SiteKind = Literal[
    "canvas_property",
    "flow_action",
    "flow_trigger",
    "table_column",
    "table_business_rule",
    "calculated_column",
    "security_role",
    "app_onstart",
]
Language = Literal["powerfx", "wdl", "dataverse_xaml", "dataverse_metadata"]


@dataclass
class FormulaSite:
    """One place in the legacy source where logic lives (a candidate business rule)."""

    site_id: str
    file: str
    kind: SiteKind
    path: str
    line: int
    language: Language
    formula: str
    screen: str = ""
    control: str = ""
    control_type: str = ""
    prop: str = ""
    description: str = ""
    ast: dict[str, Any] | None = None
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class Attribute:
    name: str
    type: str
    required: bool
    display_name: str = ""
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    calculated: bool = False
    line: int = 0


@dataclass
class Table:
    name: str
    display_name: str
    file: str
    line: int
    attributes: list[Attribute] = field(default_factory=list)


@dataclass
class Flow:
    name: str
    file: str
    trigger_kind: str
    trigger_entity: str = ""
    trigger_message: str = ""
    trigger_filter: str = ""
    actions: int = 0
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


@dataclass
class Control:
    """One canvas control, including those with no formulas (pure inputs)."""

    screen: str
    name: str
    type: str
    file: str
    line: int


@dataclass
class LegacyModel:
    app_id: str
    source: str
    sites: list[FormulaSite] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    screens: list[str] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
