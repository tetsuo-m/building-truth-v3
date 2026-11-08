"""DXF reader (ezdxf, MIT): every entity of the model space becomes a clue, values as written.

Why this way (design B-1, 3-2 B-1):
  * numbers are taken from ezdxf as floats and written to JSON with repr(), so no rounding happens;
    the unit is kept in `unit_factor` (from $INSUNITS) and applied only when reading;
  * block definitions are clues too (kind BLOCK_DEF) and their entities point at them (parent);
  * what the file did not say (code page, unit) is assumed from the project's settings and *noted*
    for intake_log (B-6: nothing is aligned or dropped silently). Jw_cad exports lack $DWGCODEPAGE
    and need ezdxf's recovery; both are noted.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import ezdxf
from ezdxf import recover
from ezdxf.tools.codepage import toencoding

from btruth.readers.base import ClueRecord, ReadResult, Reader

logging.getLogger("ezdxf").setLevel(logging.ERROR)

INSUNITS_TO_MM = {1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0, 6: 1000.0, 13: 0.001, 14: 0.01}
LAYOUT_BLOCK = re.compile(r"^\*", re.I)


def _vec(v) -> list[float]:
    return [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0]


def _plain(value):
    """Turn an ezdxf attribute value into JSON-friendly data without changing numbers."""
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    try:
        return [float(x) for x in value]
    except TypeError:
        return str(value)


class DxfReader(Reader):
    name = "dxf"
    version = f"dxf/{ezdxf.__version__}"
    formats = ("dxf",)
    note = "ezdxf で読む。モデル空間の図形とブロックの定義を手掛かりにする。値は丸めない"

    # ------------------------------------------------------------------ loading
    @staticmethod
    def _header_bytes(data: bytes) -> tuple[str | None, str | None]:
        """($ACADVER, $DWGCODEPAGE) from the raw header, without ezdxf."""
        head = data[:200000]
        ver = cp = None
        m = re.search(rb"\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*(AC\d{4})", head)
        if m:
            ver = m.group(1).decode()
        m = re.search(rb"\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*([^\r\n]+)", head)
        if m:
            cp = m.group(1).decode().strip()
        return ver, cp

    @staticmethod
    def _inject_codepage(data: bytes, codepage: str) -> bytes:
        """Give a file that says nothing about its code page the project's default (Jw_cad exports)."""
        i = data.find(b"$ACADVER")
        if i < 0:
            return data
        j = i
        for _ in range(3):                     # end of '$ACADVER' line, ' 1' line, 'AC1009' line
            j = data.find(b"\n", j) + 1
            if j <= 0:
                return data
        eol = b"\r\n" if data[:j].endswith(b"\r\n") else b"\n"
        tag = b"  9" + eol + b"$DWGCODEPAGE" + eol + b"  3" + eol + codepage.encode("ascii") + eol
        return data[:j] + tag + data[j:]

    def _load(self, data: bytes, settings: dict, notes: list):
        ver, declared = self._header_bytes(data)
        default_cp = settings.get("dxf_default_codepage") or "ANSI_932"
        if ver and ver >= "AC1021":
            encoding, note = "utf-8", {"declared": declared, "encoding": "utf-8", "reason": "DXF 2007 以降は UTF-8"}
        elif declared:
            encoding, note = toencoding(declared), {"declared": declared, "encoding": toencoding(declared)}
        else:
            encoding = toencoding(default_cp)
            note = {"declared": None, "assumed": default_cp, "encoding": encoding,
                    "reason": "ファイルに $DWGCODEPAGE がないので物件の設定を使った"}
            data = self._inject_codepage(data, default_cp)
        notes.append(("文字コード", note))
        try:
            doc = ezdxf.read(io.TextIOWrapper(io.BytesIO(data), encoding=encoding, errors="surrogateescape"))
            return doc
        except Exception as first:            # e.g. Jw_cad: table entries without a name
            doc, auditor = recover.read(io.BytesIO(data))
            notes.append(("読み込みの修復", {
                "first_error": f"{type(first).__name__}: {first}"[:300],
                "errors": len(auditor.errors), "fixes": len(auditor.fixes),
                "messages": [str(m) for m in (list(auditor.errors) + list(auditor.fixes))[:20]],
            }))
            return doc

    # ------------------------------------------------------------------ entities
    @staticmethod
    def _style(e) -> dict:
        s = {}
        for key in ("color", "linetype", "lineweight", "true_color", "ltscale", "invisible"):
            if e.dxf.hasattr(key):
                s[key] = _plain(e.dxf.get(key))
        return s

    def _geometry(self, e) -> tuple[dict, str | None, dict]:
        """(geometry, text_raw, style additions) for one entity."""
        t = e.dxftype()
        d = e.dxf
        g: dict = {}
        text = None
        style: dict = {}
        if t == "LINE":
            g = {"start": _vec(d.start), "end": _vec(d.end)}
        elif t == "CIRCLE":
            g = {"center": _vec(d.center), "radius": float(d.radius)}
        elif t == "ARC":
            g = {"center": _vec(d.center), "radius": float(d.radius),
                 "start_angle": float(d.start_angle), "end_angle": float(d.end_angle)}
        elif t == "TEXT":
            text = d.text
            g = {"insert": _vec(d.insert), "rotation": float(d.get("rotation", 0.0))}
            if d.hasattr("align_point"):
                g["align_point"] = _vec(d.align_point)
            style = {"height": _plain(d.height), "style": d.get("style", None), "width": _plain(d.get("width", 1.0)),
                     "oblique": _plain(d.get("oblique", 0.0)), "halign": d.get("halign", 0), "valign": d.get("valign", 0)}
        elif t == "MTEXT":
            text = e.text
            g = {"insert": _vec(d.insert), "rotation": float(d.get("rotation", 0.0)), "width": _plain(d.get("width", 0.0))}
            style = {"height": _plain(d.char_height), "style": d.get("style", None), "attachment_point": d.get("attachment_point", 1)}
        elif t == "INSERT":
            g = {"insert": _vec(d.insert), "xscale": float(d.get("xscale", 1.0)), "yscale": float(d.get("yscale", 1.0)),
                 "zscale": float(d.get("zscale", 1.0)), "rotation": float(d.get("rotation", 0.0))}
            style = {"block_name": d.name}
        elif t == "LWPOLYLINE":
            g = {"points": [[float(x), float(y), float(b)] for x, y, b in e.get_points(format="xyb")],
                 "closed": bool(e.closed), "elevation": float(d.get("elevation", 0.0))}
        elif t == "POLYLINE":
            g = {"points": [_vec(v.dxf.location) for v in e.vertices], "closed": bool(e.is_closed)}
        elif t == "POINT":
            g = {"location": _vec(d.location)}
        elif t in ("SOLID", "TRACE", "3DFACE"):
            g = {"vertices": [_vec(d.get(k)) for k in ("vtx0", "vtx1", "vtx2", "vtx3") if d.hasattr(k)]}
        elif t == "ELLIPSE":
            g = {"center": _vec(d.center), "major_axis": _vec(d.major_axis), "ratio": float(d.ratio),
                 "start_param": float(d.start_param), "end_param": float(d.end_param)}
        elif t == "SPLINE":
            g = {"control_points": [_vec(p) for p in e.control_points], "degree": int(d.degree), "closed": bool(e.closed)}
        elif t == "HATCH":
            paths = []
            for p in e.paths:
                verts = getattr(p, "vertices", None)
                paths.append({"type": type(p).__name__, "vertices": [[float(v[0]), float(v[1])] for v in verts] if verts else None})
            g = {"paths": paths, "solid_fill": bool(d.solid_fill)}
            style = {"pattern_name": d.pattern_name, "pattern_scale": _plain(d.get("pattern_scale", 1.0))}
        elif t == "DIMENSION":
            text = d.get("text", None)
            g = {k: _vec(d.get(k)) for k in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint")
                 if d.hasattr(k)}
            g["dimtype"] = int(d.get("dimtype", 0))
            style = {"dimstyle": d.get("dimstyle", None)}
        else:
            skip = {"handle", "owner", "layer", "color", "linetype", "lineweight", "true_color", "paperspace"}
            g = {k: _plain(v) for k, v in e.dxfattribs().items() if k not in skip}
            if d.hasattr("text"):
                text = d.text
        return g, text, style

    def _record(self, e, parent_index: int | None, in_block: str | None) -> ClueRecord:
        g, text, style_add = self._geometry(e)
        style = self._style(e)
        style.update(style_add)
        extra = {"handle": e.dxf.get("handle", None), "dxftype": e.dxftype()}
        if in_block:
            extra["in_block_def"] = in_block
        if e.has_xdata:
            try:
                extra["xdata_appids"] = [appid for appid in e.xdata.data]
            except Exception:
                pass
        return ClueRecord(kind=e.dxftype(), layer_raw=e.dxf.get("layer", "0"), geometry=g, text_raw=text,
                          style=style, format_extra=extra, parent_index=parent_index)

    # ------------------------------------------------------------------ read
    def read(self, path: Path, settings: dict | None = None) -> ReadResult:
        settings = settings or {}
        notes: list[tuple[str, dict]] = []
        data = Path(path).read_bytes()
        doc = self._load(data, settings, notes)
        insunits = doc.header.get("$INSUNITS", None)
        if insunits in INSUNITS_TO_MM:
            unit_factor = INSUNITS_TO_MM[insunits]
            notes.append(("単位", {"insunits": insunits, "unit_factor_mm": unit_factor}))
        else:
            unit_factor = float(settings.get("dxf_default_unit_factor", "1.0") or 1.0)
            notes.append(("単位", {"insunits": insunits, "unit_factor_mm": unit_factor,
                                 "reason": "$INSUNITS がない（または 0）ので mm とみなした"}))
        result = ReadResult(format="dxf", reader_name=self.name, reader_version=self.version, unit_factor=unit_factor,
                            notes=notes)
        result.notes.append(("DXF の版", {"acadver": doc.dxfversion}))
        for e in doc.modelspace():
            result.clues.append(self._record(e, None, None))
        block_count = 0
        for block in doc.blocks:
            name = block.name
            if LAYOUT_BLOCK.match(name) or block.is_any_layout:
                continue
            block_count += 1
            b = block.block
            parent = ClueRecord(kind="BLOCK_DEF", layer_raw=b.dxf.get("layer", "0"),
                                geometry={"base_point": _vec(b.dxf.base_point)}, text_raw=name,
                                style={}, format_extra={"handle": b.dxf.get("handle", None), "flags": b.dxf.get("flags", 0)})
            result.clues.append(parent)
            parent_index = len(result.clues) - 1
            for e in block:
                result.clues.append(self._record(e, parent_index, name))
        result.notes.append(("ブロックの定義", {"count": block_count}))
        return result
