"""Dataverse parsers: Entity.xml metadata, calculated-column XAML, security roles."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from factory.analyse._lines import find_line
from factory.analyse.model import Attribute, FormulaSite, Table
from factory.common.paths import rel


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    found = el.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def parse_entity(path: Path) -> Table:
    root = ET.parse(path).getroot()  # noqa: S314
    name_el = root.find("Name")
    name = (name_el.text or "").strip() if name_el is not None else path.parent.name
    display = name_el.get("LocalizedName", name) if name_el is not None else name
    table = Table(name=name, display_name=display, file=rel(path), line=find_line(path, ("<Name",)))
    for attr in root.iter("attribute"):
        phys = attr.get("PhysicalName", "")
        disp = ""
        for dn in attr.iter("displayname"):
            if dn.get("languagecode") == "1033":
                disp = dn.get("description", "")
        max_len = _text(attr, "MaxLength") or _text(attr, "Length")
        table.attributes.append(
            Attribute(
                name=phys,
                type=_text(attr, "Type"),
                required=_text(attr, "RequiredLevel") in ("required", "systemrequired"),
                display_name=disp,
                max_length=int(max_len) if max_len.isdigit() else None,
                min_value=_num(_text(attr, "MinValue")),
                max_value=_num(_text(attr, "MaxValue")),
                calculated=_text(attr, "SourceType") in ("1", "2"),
                line=find_line(path, (f'PhysicalName="{phys}"',)),
            )
        )
    return table


_TYPE_DEFAULT_RANGES = {
    "int": (-2147483648.0, 2147483647.0),
    "decimal": (-100000000000.0, 100000000000.0),
    "money": (-922337203685477.0, 922337203685477.0),
    "float": (0.0, 1000000000.0),
}


def column_sites(table: Table, path: Path) -> Iterator[FormulaSite]:
    """Required custom columns and non-default numeric ranges are data-integrity rules."""
    for a in table.attributes:
        if not a.name.lower().startswith(("cat_", "clm_")):
            continue
        parts: list[str] = []
        if a.required:
            parts.append(f"Required({a.name})")
        lo_hi = _TYPE_DEFAULT_RANGES.get(a.type)
        if a.min_value is not None and a.max_value is not None and lo_hi is not None:
            if (a.min_value, a.max_value) != lo_hi:
                parts.append(f"Range({a.name}, {a.min_value:g}, {a.max_value:g})")
        if not parts:
            continue
        yield FormulaSite(
            site_id=f"{rel(path)}#{table.name}.{a.name}",
            file=rel(path),
            kind="table_column",
            path=f"{table.name}.{a.name}",
            line=a.line,
            language="dataverse_metadata",
            formula=" && ".join(parts),
            control=table.name,
            prop=a.name,
            description=a.display_name,
        )


_REF = re.compile(r'"(cat_\w+|clm_\w+)"')
_OP = re.compile(r"ConditionOperator\.(\w+)")


def calculated_sites(entity_dir: Path, table: Table) -> Iterator[FormulaSite]:
    """Calculated-column XAML: summarised as target := f(referenced attributes, operators)."""
    for path in sorted((entity_dir / "Formulas").glob("*.xaml")):
        target = path.stem.split("-", 1)[-1]
        text = path.read_text(encoding="utf-8-sig")
        refs = sorted({m for m in _REF.findall(text) if m.lower() != target})
        ops = sorted(set(_OP.findall(text)))
        formula = f"{target} := CALC({', '.join(refs)})" + (f" WHEN {' '.join(ops)}" if ops else "")
        yield FormulaSite(
            site_id=f"{rel(path)}#{table.name}.{target}",
            file=rel(path),
            kind="calculated_column",
            path=f"{table.name}.{target}",
            line=1,
            language="dataverse_xaml",
            formula=formula,
            control=table.name,
            prop=target,
        )


def role_sites(roles_dir: Path) -> Iterator[FormulaSite]:
    """Security roles (Roles/*.xml): one site per role listing its privileges."""
    for path in sorted(roles_dir.glob("*.xml")):
        root = ET.parse(path).getroot()  # noqa: S314
        role = root.get("name", path.stem)
        privs = [p.get("name", "") + ":" + p.get("level", "") for p in root.iter("RolePrivilege")]
        yield FormulaSite(
            site_id=f"{rel(path)}#{role}",
            file=rel(path),
            kind="security_role",
            path=role,
            line=find_line(path, ("<Role",)),
            language="dataverse_metadata",
            formula=f"Role({role}) GRANTS " + ", ".join(privs),
            control=role,
        )
