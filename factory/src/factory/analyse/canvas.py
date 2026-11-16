"""Canvas-app parsers: unpacked .msapp control JSON and .pa.yaml source."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from factory.analyse._lines import find_line
from factory.analyse.model import Control, FormulaSite
from factory.common.paths import rel

STYLE_PROP = re.compile(
    r"^(X|Y|Width|Height|ZIndex|Size|Font\w*|Italic|Underline|Strikethrough|Align|VerticalAlign|"
    r"LineHeight|Overflow|Live|Role|Padding\w*|Radius\w*|Border\w*|\w*Fill|\w*Color|\w*BorderColor|"
    r"\w*Thickness|AutoHeight|Wrap|Transition|TemplateSize|TemplatePadding|ImagePosition|"
    r"LayoutDirection|LayoutMode|LayoutAlign\w*|LayoutJustify\w*|LayoutGap|LayoutWrap|"
    r"LayoutOverflow\w*|Flexible\w*|FillPortions|AlignInContainer|Orientation|DropShadow|"
    r"ContentLanguage|Tooltip|AccessibleLabel|TabIndex|EnableChildFocus|ShowScrollbar|"
    r"DisplayMode|Icon|Image|Shadow\w*|Appearance|FontSize|Weight|Layout|Spacing|Gap)$"
)


def is_style_property(prop: str) -> bool:
    """Pure presentation properties (position, colour, typography). DisplayMode is kept below."""
    return prop != "DisplayMode" and bool(STYLE_PROP.match(prop))


def _site(
    path: Path, kind: str, screen: str, control: str, ctype: str, prop: str, formula: str, line: int
) -> FormulaSite:
    k = "app_onstart" if control == "App" and prop in ("OnStart", "Formulas") else kind
    return FormulaSite(
        site_id=(
            f"{rel(path)}#{screen}/{control}.{prop}" if screen else f"{rel(path)}#{control}.{prop}"
        ),
        file=rel(path),
        kind=k,  # type: ignore[arg-type]
        path=f"{screen}/{control}.{prop}" if screen else f"{control}.{prop}",
        line=line,
        language="powerfx",
        formula=formula,
        screen=screen,
        control=control,
        control_type=ctype,
        prop=prop,
    )


def parse_msapp_controls(app_dir: Path) -> Iterator[FormulaSite]:
    """Parse the per-control JSON files of an unpacked .msapp (Controls/*.json)."""
    for path in sorted((app_dir / "Controls").glob("*.json"), key=lambda p: int(p.stem)):
        top = json.loads(path.read_text(encoding="utf-8-sig"))["TopParent"]
        screen = "" if top["Name"] == "App" else top["Name"]
        yield from _walk_control(path, top, screen)


def _walk_control(path: Path, ctrl: dict[str, Any], screen: str) -> Iterator[FormulaSite]:
    name = ctrl["Name"]
    ctype = ctrl.get("Template", {}).get("Name", "")
    name_line = find_line(path, (f'"Name": "{name}"',)) - 1
    for rule in ctrl.get("Rules", []):
        prop, formula = rule["Property"], rule.get("InvariantScript", "")
        if not formula.strip():
            continue
        line = find_line(path, (f'"Property": "{prop}"', '"InvariantScript"'), start=name_line)
        yield _site(path, "canvas_property", screen, name, ctype, prop, formula, line)
    for child in ctrl.get("Children", []):
        yield from _walk_control(path, child, screen)


def parse_pa_yaml(src_dir: Path) -> Iterator[FormulaSite]:
    """Parse Power Apps YAML source (*.pa.yaml): App / Screens / Children / Properties."""
    for path in sorted(src_dir.rglob("*.pa.yaml")):
        root = yaml.compose(path.read_text(encoding="utf-8"))
        if not isinstance(root, yaml.MappingNode):
            continue
        for key, val in root.value:
            if key.value == "App":
                yield from _yaml_control(path, "", "App", "appinfo", val)
            elif key.value in ("Screens", "Components"):
                for skey, sval in _mapping(val):
                    yield from _yaml_control(path, skey.value, skey.value, "screen", sval)


def _mapping(node: yaml.Node) -> list[tuple[yaml.ScalarNode, yaml.Node]]:
    return list(node.value) if isinstance(node, yaml.MappingNode) else []


def _yaml_control(
    path: Path, screen: str, name: str, ctype: str, node: yaml.Node
) -> Iterator[FormulaSite]:
    for key, val in _mapping(node):
        if key.value == "Control" and isinstance(val, yaml.ScalarNode):
            ctype = val.value.split("@")[0]
    for key, val in _mapping(node):
        if key.value == "Properties":
            for pkey, pval in _mapping(val):
                if isinstance(pval, yaml.ScalarNode) and pval.value.startswith("="):
                    line = pval.start_mark.line + 1
                    formula = pval.value[1:].strip()
                    yield _site(
                        path, "canvas_property", screen, name, ctype, pkey.value, formula, line
                    )
        elif key.value == "Children" and isinstance(val, yaml.SequenceNode):
            for item in val.value:
                for ckey, cval in _mapping(item):
                    yield from _yaml_control(path, screen, ckey.value, "", cval)


def list_controls(app_dir: Path, fmt: str) -> Iterator[Control]:
    """Every control with its type and source line, whether or not it has formulas."""
    if fmt == "msapp_json":
        for path in sorted((app_dir / "Controls").glob("*.json"), key=lambda p: int(p.stem)):
            top = json.loads(path.read_text(encoding="utf-8-sig"))["TopParent"]
            stack: list[tuple[dict[str, Any], str]] = [(top, top["Name"])]
            while stack:
                ctrl, screen = stack.pop()
                name = ctrl["Name"]
                line = find_line(path, (f'"Name": "{name}"',))
                ctype = ctrl.get("Template", {}).get("Name", "")
                yield Control(screen, name, ctype, rel(path), line)
                stack.extend((c, screen) for c in reversed(ctrl.get("Children", [])))
        return
    for path in sorted(app_dir.rglob("*.pa.yaml")):
        root = yaml.compose(path.read_text(encoding="utf-8"))
        for key, val in _mapping(root) if root is not None else []:
            if key.value not in ("Screens", "Components"):
                continue
            for skey, sval in _mapping(val):
                yield Control(skey.value, skey.value, "screen", rel(path), skey.start_mark.line + 1)
                yield from _yaml_children(path, skey.value, sval)


def _yaml_children(path: Path, screen: str, node: yaml.Node) -> Iterator[Control]:
    for key, val in _mapping(node):
        if key.value != "Children" or not isinstance(val, yaml.SequenceNode):
            continue
        for item in val.value:
            for ckey, cval in _mapping(item):
                ctype = next(
                    (v.value.split("@")[0] for k, v in _mapping(cval)
                     if k.value == "Control" and isinstance(v, yaml.ScalarNode)),
                    "",
                )  # fmt: skip
                yield Control(screen, ckey.value, ctype, rel(path), ckey.start_mark.line + 1)
                yield from _yaml_children(path, screen, cval)
