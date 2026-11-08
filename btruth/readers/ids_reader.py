"""The IDS reader (design L-1; buildingSMART Information Delivery Specification, XML).

A rule reader: one clue per specification (kind SPECIFICATION, text_raw = the specification's XML), nothing else.
The intake then makes one `condition` row per specification (form = ids) with the applicability and the requirements
normalised into `ids_json` (the six facets: entity, attribute, classification, property, material, partOf).
Accepts IDS 1.0 (`baseName`) and older drafts (`name` for a property's name). Standard library only.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from btruth.readers.base import ClueRecord, Reader, ReadResult

NS = "{http://standards.buildingsmart.org/IDS}"
FACETS = ("entity", "attribute", "classification", "property", "material", "partOf")


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _value(el) -> dict | str | None:
    """An IDS value: simpleValue → the text; xs:restriction with enumerations → {"enum": [...]}; pattern → {"pattern"}."""
    if el is None:
        return None
    sv = _child(el, "simpleValue")
    if sv is not None:
        return (sv.text or "").strip()
    for c in el:
        if _local(c.tag) == "restriction":
            enum = [e.get("value") for e in c if _local(e.tag) == "enumeration"]
            if enum:
                return {"enum": enum}
            pat = next((e.get("value") for e in c if _local(e.tag) == "pattern"), None)
            if pat:
                return {"pattern": pat}
            rng = {_local(e.tag): e.get("value") for e in c if _local(e.tag) in ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive")}
            if rng:
                return {"range": rng}
    return None


def facet(el) -> dict:
    kind = _local(el.tag)
    d: dict = {"facet": kind}
    if kind == "entity":
        d["name"] = _value(_child(el, "name"))
        d["predefinedType"] = _value(_child(el, "predefinedType"))
    elif kind == "attribute":
        d["name"] = _value(_child(el, "name"))
        d["value"] = _value(_child(el, "value"))
    elif kind == "property":
        d["propertySet"] = _value(_child(el, "propertySet"))
        d["baseName"] = _value(_child(el, "baseName")) or _value(_child(el, "name"))
        d["value"] = _value(_child(el, "value"))
    elif kind == "classification":
        d["system"] = _value(_child(el, "system"))
        d["value"] = _value(_child(el, "value"))
    elif kind == "material":
        d["value"] = _value(_child(el, "value"))
    elif kind == "partOf":
        d["relation"] = el.get("relation")
        ent = _child(el, "entity")
        d["entity"] = _value(_child(ent, "name")) if ent is not None else None
    if el.get("cardinality"):
        d["cardinality"] = el.get("cardinality")
    return {k: v for k, v in d.items() if v is not None or k in ("value",)}


def specification_json(spec) -> dict:
    app = _child(spec, "applicability")
    req = _child(spec, "requirements")
    applicability: dict = {f: [] for f in FACETS}
    for el in (app if app is not None else []):
        f = facet(el)
        k = f["facet"]
        applicability[k].append(f.get("name") if k == "entity" else {x: y for x, y in f.items() if x != "facet"})
    requirements = []
    for el in (req if req is not None else []):
        f = facet(el)
        f.setdefault("cardinality", "required")
        if f["facet"] == "property":
            f = {"facet": "property", "propertySet": f.get("propertySet"), "baseName": f.get("baseName"),
                 "cardinality": f["cardinality"], "value": f.get("value")}
        requirements.append(f)
    return {"name": spec.get("name"), "ifcVersion": spec.get("ifcVersion"),
            "applicability": {k: v for k, v in applicability.items() if v}, "requirements": requirements}


class IdsReader(Reader):
    name = "ids"
    version = "ids/1"
    formats = ("ids",)
    note = "IDS の specification を SPECIFICATION の手掛かりにする（条件の行は取り込みが作る。L-1）"

    def read(self, path: Path, settings: dict | None = None) -> ReadResult:
        data = Path(path).read_bytes()
        root = ET.fromstring(data)
        result = ReadResult(format="ids", reader_name=self.name, reader_version=self.version, unit_factor=1.0, notes=[])
        info = _child(root, "info")
        purpose = (_child(info, "purpose").text or "").strip() if info is not None and _child(info, "purpose") is not None else None
        title = (_child(info, "title").text or "").strip() if info is not None and _child(info, "title") is not None else None
        result.notes.append(("IDS", {"title": title, "purpose": purpose}))
        specs = _child(root, "specifications")
        for spec in (specs if specs is not None else []):
            if _local(spec.tag) != "specification":
                continue
            result.clues.append(ClueRecord(kind="SPECIFICATION", layer_raw=None, geometry=None,
                                           text_raw=ET.tostring(spec, encoding="unicode"), style=None,
                                           format_extra={"ids": specification_json(spec), "purpose": purpose, "title": title}))
        return result
