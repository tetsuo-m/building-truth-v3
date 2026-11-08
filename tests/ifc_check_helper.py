"""Run by a Python that has IfcOpenShell (not a dependency of btruth): validate IFC files and build their shapes.
Prints one JSON line per file: {"file", "schema", "problems": [...], "shapes_ok", "shapes_failed"}."""
import json
import sys

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

for name in sys.argv[1:]:
    f = ifcopenshell.open(name)
    logger = ifcopenshell.validate.json_logger()
    try:
        ifcopenshell.validate.validate(f, logger, express_rules=True)
    except ModuleNotFoundError:                       # the EXPRESS rules need pytest; the schema checks still run
        ifcopenshell.validate.validate(f, logger)
    ok = bad = 0
    settings = ifcopenshell.geom.settings()
    for e in f.by_type("IfcProduct"):
        if e.Representation is None:
            continue
        try:
            ifcopenshell.geom.create_shape(settings, e)
            ok += 1
        except Exception:
            bad += 1
    print(json.dumps({"file": name, "schema": f.schema, "problems": [str(s.get("message"))[:300] for s in logger.statements],
                      "shapes_ok": ok, "shapes_failed": bad}, ensure_ascii=False))
