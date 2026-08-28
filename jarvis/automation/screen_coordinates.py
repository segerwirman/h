"""Pure coordinate mapping for mixed-DPI virtual desktop layouts.

The mapper is deliberately independent from Qt, UIA, MSS, and native pointer
APIs. Callers inject complete logical and physical monitor geometry. Agent
schemas never import or expose this module; only trusted capture/execution and
visualization boundaries use it.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

Point = tuple[int, int]
Rect = tuple[int, int, int, int]
CoordinateSpace = str


class CoordinateMappingError(ValueError):
    """A point or rectangle cannot be mapped unambiguously and safely."""


@dataclass(frozen=True)
class MonitorGeometry:
    """One monitor represented in both logical and physical desktop spaces."""

    name: str
    logical_rect: Rect
    physical_rect: Rect
    dpi_scale: float

    def __post_init__(self) -> None:
        logical = _rect(self.logical_rect)
        physical = _rect(self.physical_rect)
        scale = float(self.dpi_scale)
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("DPI scale monitor harus finite dan positif")
        expected_width = logical[2] * scale
        expected_height = logical[3] * scale
        if (
            abs(physical[2] - expected_width) > 1.0
            or abs(physical[3] - expected_height) > 1.0
        ):
            raise ValueError("geometri logical/physical tidak cocok dengan DPI scale")
        object.__setattr__(self, "name", str(self.name or "monitor"))
        object.__setattr__(self, "logical_rect", logical)
        object.__setattr__(self, "physical_rect", physical)
        object.__setattr__(self, "dpi_scale", scale)

    def rect_for(self, space: CoordinateSpace) -> Rect:
        normalized = _space(space)
        return self.logical_rect if normalized == "logical" else self.physical_rect


class ScreenCoordinateMapper:
    """Map points and rectangles using an injected monitor-layout provider.

    ``uia_space`` states what coordinate space an injected UIA backend emits.
    Native Windows UIA normally emits physical screen coordinates, so the
    production-safe default is physical identity. Tests and DPI-virtualized
    backends may inject ``uia_space="logical"`` with explicit monitor geometry.
    """

    def __init__(
        self,
        monitor_provider: Callable[[], Iterable[MonitorGeometry]] | None = None,
        *,
        uia_space: CoordinateSpace = "physical",
    ) -> None:
        self._monitor_provider = monitor_provider or (lambda: ())
        self.uia_space = _space(uia_space)

    def map_point(
        self,
        point: Point,
        *,
        source_space: CoordinateSpace,
        target_space: CoordinateSpace,
    ) -> Point:
        source = _space(source_space)
        target = _space(target_space)
        normalized = _point(point)
        if source == target:
            return normalized
        monitor = self._monitor_for_point(normalized, source)
        return _map_point_on_monitor(normalized, monitor, source, target)

    def map_rect(
        self,
        rect: Rect,
        *,
        source_space: CoordinateSpace,
        target_space: CoordinateSpace,
    ) -> Rect:
        source = _space(source_space)
        target = _space(target_space)
        normalized = _rect(rect)
        if source == target:
            return normalized
        monitor = self._monitor_for_rect(normalized, source)
        x, y, width, height = normalized
        left, top = _map_point_on_monitor((x, y), monitor, source, target)
        right, bottom = _map_edge_on_monitor(
            (x + width, y + height), monitor, source, target
        )
        mapped = (left, top, right - left, bottom - top)
        if mapped[2] <= 0 or mapped[3] <= 0:
            raise CoordinateMappingError("rectangle hasil mapping tidak positif")
        return mapped

    def to_physical(
        self,
        point: Point,
        *,
        source_space: CoordinateSpace | None = None,
    ) -> Point:
        return self.map_point(
            point,
            source_space=source_space or self.uia_space,
            target_space="physical",
        )

    def to_logical(self, point: Point) -> Point:
        return self.map_point(
            point,
            source_space="physical",
            target_space="logical",
        )

    def rect_center_to_physical(
        self,
        rect: Rect,
        *,
        source_space: CoordinateSpace | None = None,
    ) -> Point:
        x, y, width, height = _rect(rect)
        center = (x + width // 2, y + height // 2)
        return self.to_physical(center, source_space=source_space or self.uia_space)

    def _monitors(self) -> tuple[MonitorGeometry, ...]:
        try:
            monitors = tuple(self._monitor_provider())
        except Exception as exc:
            raise CoordinateMappingError(
                f"provider monitor gagal: {type(exc).__name__}"
            ) from exc
        if not monitors:
            raise CoordinateMappingError("geometri monitor tidak tersedia")
        if not all(isinstance(item, MonitorGeometry) for item in monitors):
            raise CoordinateMappingError("provider monitor mengembalikan geometri tidak valid")
        return monitors

    def _monitor_for_point(self, point: Point, space: CoordinateSpace) -> MonitorGeometry:
        matches = [
            monitor
            for monitor in self._monitors()
            if _contains_point(monitor.rect_for(space), point)
        ]
        if len(matches) != 1:
            raise CoordinateMappingError("point tidak terikat tepat ke satu monitor")
        return matches[0]

    def _monitor_for_rect(self, rect: Rect, space: CoordinateSpace) -> MonitorGeometry:
        matches = [
            monitor
            for monitor in self._monitors()
            if _contains_rect(monitor.rect_for(space), rect)
        ]
        if len(matches) != 1:
            raise CoordinateMappingError("rectangle harus berada pada tepat satu monitor")
        return matches[0]


def _space(value: CoordinateSpace) -> CoordinateSpace:
    normalized = str(value or "").strip().casefold()
    if normalized not in {"logical", "physical"}:
        raise CoordinateMappingError("coordinate space harus logical atau physical")
    return normalized


def _point(value) -> Point:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise CoordinateMappingError("point harus berisi x dan y")
    try:
        x, y = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise CoordinateMappingError("point harus numerik") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise CoordinateMappingError("point harus finite")
    return int(round(x)), int(round(y))


def _rect(value) -> Rect:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise CoordinateMappingError("rectangle harus berisi x, y, width, height")
    try:
        raw = tuple(float(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise CoordinateMappingError("rectangle harus numerik") from exc
    if not all(math.isfinite(part) for part in raw):
        raise CoordinateMappingError("rectangle harus finite")
    x, y, width, height = (int(round(part)) for part in raw)
    if width <= 0 or height <= 0:
        raise CoordinateMappingError("width dan height rectangle harus positif")
    return x, y, width, height


def _contains_point(rect: Rect, point: Point) -> bool:
    x, y, width, height = rect
    px, py = point
    return x <= px < x + width and y <= py < y + height


def _contains_rect(outer: Rect, inner: Rect) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (
        ox <= ix
        and oy <= iy
        and ix + iw <= ox + ow
        and iy + ih <= oy + oh
    )


def _map_point_on_monitor(
    point: Point,
    monitor: MonitorGeometry,
    source_space: CoordinateSpace,
    target_space: CoordinateSpace,
) -> Point:
    source = monitor.rect_for(source_space)
    target = monitor.rect_for(target_space)
    sx, sy, sw, sh = source
    tx, ty, tw, th = target
    px, py = point
    return (
        int(round(tx + (px - sx) * tw / sw)),
        int(round(ty + (py - sy) * th / sh)),
    )


def _map_edge_on_monitor(
    point: Point,
    monitor: MonitorGeometry,
    source_space: CoordinateSpace,
    target_space: CoordinateSpace,
) -> Point:
    """Map an exclusive rectangle edge, including a monitor's right/bottom."""
    return _map_point_on_monitor(point, monitor, source_space, target_space)


COORDINATES = ScreenCoordinateMapper()


def map_point(
    point: Point,
    *,
    source_space: CoordinateSpace,
    target_space: CoordinateSpace,
) -> Point:
    return COORDINATES.map_point(
        point,
        source_space=source_space,
        target_space=target_space,
    )


def map_rect(
    rect: Rect,
    *,
    source_space: CoordinateSpace,
    target_space: CoordinateSpace,
) -> Rect:
    return COORDINATES.map_rect(
        rect,
        source_space=source_space,
        target_space=target_space,
    )


def to_physical(
    point: Point,
    *,
    source_space: CoordinateSpace | None = None,
) -> Point:
    return COORDINATES.to_physical(point, source_space=source_space)


__all__ = [
    "COORDINATES",
    "CoordinateMappingError",
    "MonitorGeometry",
    "ScreenCoordinateMapper",
    "map_point",
    "map_rect",
    "to_physical",
]
