"""Plane geometry used by the rule checks and the output calculations (design C-2c, C-2e, E-3, B-10).

Everything here is computed on demand; nothing is stored. Lengths are in the drawing's unit (mm).
Coordinates may be large (Jw_cad exports sit near 2e8), so areas are computed after shifting to a local
origin to keep double precision.
"""
from __future__ import annotations

import math

Point = tuple[float, float]
Segment = tuple[Point, Point]


def segment(value) -> Segment | None:
    """A 線分 / 芯線 value [[x1, y1(, z)], [x2, y2(, z)]] as two points, or None if it is not one."""
    try:
        (a, b) = value
        return (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
    except (TypeError, ValueError, IndexError):
        return None


def length(seg: Segment) -> float:
    return math.dist(seg[0], seg[1])


def _unit(seg: Segment) -> Point:
    L = length(seg)
    if L == 0:
        return (0.0, 0.0)
    return ((seg[1][0] - seg[0][0]) / L, (seg[1][1] - seg[0][1]) / L)


def along(seg: Segment, p: Point) -> float:
    """Distance of the projection of p onto the line of seg, measured from seg's start."""
    u = _unit(seg)
    return (p[0] - seg[0][0]) * u[0] + (p[1] - seg[0][1]) * u[1]


def distance_to_line(seg: Segment, p: Point) -> float:
    u = _unit(seg)
    return abs((p[0] - seg[0][0]) * u[1] - (p[1] - seg[0][1]) * u[0])


def overlap_on(base: Segment, other: Segment, tol: float) -> tuple[float, float] | None:
    """The interval of `base` (distances from its start) covered by `other`, if `other` lies on the same
    line (both endpoints within `tol` of the line) and the overlap has a positive length. None otherwise.
    This is how the partner interval of a boundary is computed (C-2c): never stored, always derived."""
    if length(base) == 0:
        return None
    if distance_to_line(base, other[0]) > tol or distance_to_line(base, other[1]) > tol:
        return None
    t0, t1 = sorted((along(base, other[0]), along(base, other[1])))
    lo, hi = max(0.0, t0), min(length(base), t1)
    if hi - lo <= tol:
        return None
    return (lo, hi)


def merge_intervals(intervals: list[tuple[float, float]], tol: float = 0.0) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def gaps(total: tuple[float, float], covered: list[tuple[float, float]], min_gap: float) -> list[tuple[float, float]]:
    """Parts of `total` not covered by `covered`, longer than `min_gap`."""
    lo, hi = total
    result = []
    pos = lo
    for a, b in merge_intervals(covered):
        if a - pos > min_gap:
            result.append((pos, a))
        pos = max(pos, b)
    if hi - pos > min_gap:
        result.append((pos, hi))
    return result


def polygon_area(points: list[Point]) -> float:
    """Signed shoelace area (positive = counter-clockwise), computed at a local origin."""
    if len(points) < 3:
        return 0.0
    ox, oy = points[0]
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i][0] - ox, points[i][1] - oy
        x2, y2 = points[(i + 1) % n][0] - ox, points[(i + 1) % n][1] - oy
        s += x1 * y2 - x2 * y1
    return s / 2.0


def chain(segments: list[Segment], tol: float) -> list[Point] | None:
    """Order segments into one closed ring (end of one meets start of the next within `tol`; a segment may
    be reversed). Returns the ring's corner points, or None if the segments do not close into one ring."""
    if not segments:
        return None
    rest = list(segments[1:])
    ring = [segments[0][0], segments[0][1]]
    while rest:
        tail = ring[-1]
        found = None
        for i, s in enumerate(rest):
            if math.dist(s[0], tail) <= tol:
                found, nxt = i, s[1]
                break
            if math.dist(s[1], tail) <= tol:
                found, nxt = i, s[0]
                break
        if found is None:
            return None
        rest.pop(found)
        ring.append(nxt)
    if math.dist(ring[-1], ring[0]) > tol:
        return None
    return ring[:-1]


def ring_from_ordered(segments: list[Segment], tol: float) -> list[Point] | None:
    """The corners of a ring whose segments are already in walking order (区切る の 順)."""
    for i, s in enumerate(segments):
        nxt = segments[(i + 1) % len(segments)]
        if math.dist(s[1], nxt[0]) > tol:
            return None
    return [s[0] for s in segments]
