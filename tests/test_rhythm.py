from datetime import datetime
import random

from hub.control_hub.domain import default_settings, validate_settings
from hub.control_hub.rhythm import RhythmEngine


def rhythm_settings():
    settings = default_settings()
    settings["profile"] = "developer_clt"
    settings["lunch_start"] = "12:00"
    settings["lunch_end"] = "13:00"
    settings["lunch_jitter_minutes"] = 0
    settings["coffee_break_count"] = 0
    settings["work_start_jitter_minutes"] = 0
    return validate_settings(settings)


def test_rhythm_pauses_during_lunch():
    now = datetime(2026, 7, 6, 12, 15)
    engine = RhythmEngine(rng=random.Random(1), now_provider=lambda: now)

    state = engine.evaluate(rhythm_settings())

    assert state.is_pause is True
    assert state.pause_type == "lunch"
    assert state.pause_seconds == 45 * 60


def test_rhythm_energy_rises_after_work_start():
    settings = rhythm_settings()
    early = RhythmEngine(rng=random.Random(2), now_provider=lambda: datetime(2026, 7, 6, 9, 10)).evaluate(settings)
    late_morning = RhythmEngine(rng=random.Random(2), now_provider=lambda: datetime(2026, 7, 6, 10, 45)).evaluate(settings)

    assert 0.5 < early.energy < late_morning.energy <= 1.0


def test_rhythm_focus_mode_boosts_vscode_weight():
    engine = RhythmEngine(rng=random.Random(5), now_provider=lambda: datetime(2026, 7, 6, 10, 30))
    state = engine.evaluate(rhythm_settings())

    if state.mode == "focus":
        assert state.routine_multipliers["vscode_type_random_text"] > 1.0
    assert state.next_interval_seconds({"min_interval_seconds": 60, "max_interval_seconds": 180}) >= 60
