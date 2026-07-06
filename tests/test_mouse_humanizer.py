import random
from types import SimpleNamespace

import pytest

from windows_agent.mouse_humanizer import bezier_path, choose_interest_point, interest_zones, overshoot_point, safe_bounds


def test_choose_interest_point_stays_inside_safe_bounds():
    fake_pyautogui = SimpleNamespace(size=lambda: (1920, 1080))

    x, y = choose_interest_point(fake_pyautogui, margin=120, rng=random.Random(3))

    left, top, right, bottom = safe_bounds(1920, 1080, 120)
    assert left <= x <= right
    assert top <= y <= bottom


def test_interest_zones_include_weighted_work_areas():
    zones = interest_zones(1920, 1080, 100)
    names = {zone.name for zone in zones}

    assert names == {"center", "taskbar", "top", "left", "right"}
    assert sum(zone.weight for zone in zones) == pytest.approx(1.0)


def test_bezier_path_preserves_start_and_end_with_micro_steps():
    path = bezier_path((10, 20), (300, 240), steps=60, rng=random.Random(4))

    assert path[0].x == 10
    assert path[0].y == 20
    assert path[-1].x == 300
    assert path[-1].y == 240
    assert len(path) == 61
    assert len({(point.x, point.y) for point in path}) > 40


def test_overshoot_point_remains_inside_safe_bounds():
    point = overshoot_point((100, 100), (1800, 900), 1920, 1080, 100, random.Random(8))
    left, top, right, bottom = safe_bounds(1920, 1080, 100)

    assert left <= point[0] <= right
    assert top <= point[1] <= bottom
