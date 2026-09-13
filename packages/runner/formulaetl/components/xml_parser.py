"""XML Parser — basic XML records → row dicts (tag / simple path lite)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _elem_to_row(elem: ET.Element, include_attrs: bool) -> dict[str, Any]:
    row: dict[str, Any] = {}
    if include_attrs:
        for k, v in elem.attrib.items():
            row[f"@{_local(k)}"] = v
    # Direct child text fields
    for child in list(elem):
        name = _local(child.tag)
        text = (child.text or "").strip()
        # Nested children → flatten one level as name_child
        grandchildren = list(child)
        if grandchildren:
            for gc in grandchildren:
                gname = f"{name}_{_local(gc.tag)}"
                row[gname] = (gc.text or "").strip()
            if text:
                row[name] = text
        else:
            if name in row and row[name] not in (None, ""):
                # duplicate tags → list-ish join
                row[name] = f"{row[name]};{text}"
            else:
                row[name] = text
            if include_attrs:
                for k, v in child.attrib.items():
                    row[f"{name}@{_local(k)}"] = v
    # If no children, use element text
    if not list(elem) and (elem.text or "").strip():
        row["value"] = (elem.text or "").strip()
    return row


def _find_records(root: ET.Element, record_tag: str | None, xpath: str | None) -> list[ET.Element]:
    if xpath:
        path = xpath.strip()
        if path.startswith(".//"):
            tag = path[3:].split("/")[0]
            return [e for e in root.iter() if _local(e.tag) == tag]
        try:
            found = root.findall(path)
            if found:
                return list(found)
        except Exception:
            pass
        tag = path.rstrip("/").split("/")[-1]
        return [e for e in root.iter() if _local(e.tag) == tag]

    if record_tag:
        tag = record_tag.strip()
        return [e for e in root.iter() if _local(e.tag) == tag]

    kids = list(root)
    if kids:
        return kids
    return [root]


@register
class XMLParser(BaseComponent):
    component_type = "xml_parser"
    display_name = "XML Parser"
    category = "transform"
    config_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "record_tag": {
                "type": "string",
                "description": "Element local name for each record, e.g. order",
            },
            "xpath": {
                "type": "string",
                "description": "Lite path e.g. .//order or /orders/order",
            },
            "include_attrs": {"type": "boolean", "default": True},
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "XML file path",
            "type": "string",
            "required": False,
            "help": "Read XML from this file",
        },
        {
            "key": "content",
            "label": "Inline XML",
            "type": "string",
            "required": False,
            "help": "Inline XML text (or upstream content/bytes)",
        },
        {
            "key": "record_tag",
            "label": "Record tag",
            "type": "string",
            "required": False,
            "default": "record",
            "help": "Local element name for each row (e.g. order, item, record)",
        },
        {
            "key": "xpath",
            "label": "XPath (lite)",
            "type": "string",
            "required": False,
            "help": "Optional lite path: .//order or /orders/order",
        },
        {
            "key": "include_attrs",
            "label": "Include attributes",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Map XML attributes as @attr / field@attr columns",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            content: str | None = self.config.get("content")
            if content is None and self.config.get("path"):
                p = ctx.resolve(self.config["path"])
                if not p.exists():
                    raise FileNotFoundError(f"XMLParser: file not found: {p}")
                content = p.read_text(encoding="utf-8")
            if content is None and ctx.variables.get("upstream_content"):
                content = ctx.variables["upstream_content"]
            if content is None and ctx.variables.get("upstream_bytes"):
                b = ctx.variables["upstream_bytes"]
                content = b.decode("utf-8") if isinstance(b, bytes) else str(b)
            if content is None and rows and len(rows) == 1 and isinstance(rows[0].get("content"), str):
                content = rows[0]["content"]
            if content is None:
                raise ValueError("XMLParser: no XML content available")

            root = ET.fromstring(content)
            record_tag = self.config.get("record_tag")
            xpath = self.config.get("xpath")
            include_attrs = bool(self.config.get("include_attrs", True))
            elems = _find_records(root, record_tag, xpath)
            # Deduplicate while preserving order (iter can overlap findall)
            seen: set[int] = set()
            unique: list[ET.Element] = []
            for e in elems:
                i = id(e)
                if i not in seen:
                    seen.add(i)
                    unique.append(e)

            out_rows = [_elem_to_row(e, include_attrs) for e in unique]
            metrics.rows_in = 1
            metrics.rows_out = len(out_rows)
            ctx.emit(f"XMLParser: {len(out_rows)} records (tag={record_tag!r} xpath={xpath!r})")

        return ComponentResult(rows=out_rows, metrics=metrics)
