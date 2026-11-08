"""Small shared helpers: ids, time stamps, hashes, JSON that keeps numbers exact."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from pathlib import Path


def new_id() -> str:
    """An id without meaning (0-2, E-6): UUID v4 as a 36-character string (decision Q3)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 with the local time zone (0-2)."""
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(obj) -> str:
    """JSON for *_json columns. Python's json writes floats with repr(), the shortest text that
    reads back to exactly the same value, so nothing is rounded (B-1, B-14)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(text: str | None):
    return None if text is None else json.loads(text)
