from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Zone:
    name: str
    left: int
    top: int
    right: int
    bottom: int
    weight: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def safe_bounds(width: int, height: int, margin: int) -> tuple[int, int, int, int]:
    max_margin_x = max(1, (int(width) - 1) // 2)
    max_margin_y = max(1, (int(height) - 1) // 2)
    safe_margin = max(1, min(int(margin), max_margin_x, max_margin_y))
    return (
        safe_margin,
        safe_margin,
        max(safe_margin, int(width) - safe_margin - 1),
        max(safe_margin, int(height) - safe_margin - 1),
    )


def interest_zones(width: int, height: int, margin: int) -> list[Zone]:
    left, top, right, bottom = safe_bounds(width, height, margin)
    usable_width = max(1, right - left)
    usable_height = max(1, bottom - top)
    return [
        Zone(
            "center",
            left + int(usable_width * 0.22),
            top + int(usable_height * 0.18),
            left + int(usable_width * 0.78),
            top + int(usable_height * 0.78),
            0.40,
        ),
        Zone("taskbar", left, top + int(usable_height * 0.86), right, bottom, 0.15),
        Zone("top", left + int(usable_width * 0.08), top, left + int(usable_width * 0.92), top + int(usable_height * 0.18), 0.10),
        Zone("left", left, top + int(usable_height * 0.10), left + int(usable_width * 0.22), top + int(usable_height * 0.86), 0.175),
        Zone("right", left + int(usable_width * 0.78), top + int(usable_height * 0.10), right, top + int(usable_height * 0.86), 0.175),
    ]


def choose_interest_point(
    pyautogui: Any,
    margin: int,
    rng: random.Random | None = None,
) -> tuple[int, int]:
    rng = rng or random
    width, height = pyautogui.size()
    zones = interest_zones(int(width), int(height), int(margin))
    zone = rng.choices(zones, weights=[item.weight for item in zones], k=1)[0]
    center_x, center_y = zone.center
    spread_x = max(1.0, (zone.right - zone.left) / 4)
    spread_y = max(1.0, (zone.bottom - zone.top) / 4)
    x = int(round(clamp(rng.gauss(center_x, spread_x), zone.left, zone.right)))
    y = int(round(clamp(rng.gauss(center_y, spread_y), zone.top, zone.bottom)))
    safe_left, safe_top, safe_right, safe_bottom = safe_bounds(int(width), int(height), int(margin))
    return (
        int(clamp(x, safe_left, safe_right)),
        int(clamp(y, safe_top, safe_bottom)),
    )


def ease_in_out(t: float) -> float:
    return (1 - math.cos(math.pi * clamp(t, 0.0, 1.0))) / 2


def cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1 - t
    x = (u**3 * p0[0]) + (3 * u**2 * t * p1[0]) + (3 * u * t**2 * p2[0]) + (t**3 * p3[0])
    y = (u**3 * p0[1]) + (3 * u**2 * t * p1[1]) + (3 * u * t**2 * p2[1]) + (t**3 * p3[1])
    return x, y


def bezier_path(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int,
    rng: random.Random | None = None,
) -> list[Point]:
    rng = rng or random
    steps = max(2, int(steps))
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    distance = max(1.0, math.hypot(dx, dy))
    normal_x = -dy / distance
    normal_y = dx / distance
    bend = rng.gauss(0, min(140.0, distance * 0.18))
    p0 = (float(sx), float(sy))
    p3 = (float(ex), float(ey))
    p1 = (sx + dx * 0.28 + normal_x * bend, sy + dy * 0.28 + normal_y * bend)
    p2 = (sx + dx * 0.72 - normal_x * bend * 0.55, sy + dy * 0.72 - normal_y * bend * 0.55)
    noise = min(5.0, max(0.6, distance * 0.006))
    points: list[Point] = []
    for index in range(steps + 1):
        t = ease_in_out(index / steps)
        x, y = cubic_bezier(p0, p1, p2, p3, t)
        if 0 < index < steps:
            x += normal_x * rng.gauss(0, noise)
            y += normal_y * rng.gauss(0, noise)
        points.append(Point(int(round(x)), int(round(y))))
    return points


def overshoot_point(
    start: tuple[int, int],
    end: tuple[int, int],
    width: int,
    height: int,
    margin: int,
    rng: random.Random | None = None,
) -> tuple[int, int]:
    rng = rng or random
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    distance = max(1.0, math.hypot(dx, dy))
    extension = rng.uniform(0.03, 0.08) * distance
    x = ex + (dx / distance) * extension
    y = ey + (dy / distance) * extension
    left, top, right, bottom = safe_bounds(width, height, margin)
    return int(clamp(x, left, right)), int(clamp(y, top, bottom))
