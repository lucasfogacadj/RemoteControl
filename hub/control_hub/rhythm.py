from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
import random
from typing import Any, Callable


PROFILE_WINDOWS = {
    "developer_clt": (9 * 60, 18 * 60),
    "developer_remote": (8 * 60 + 30, 18 * 60 + 30),
    "freelancer": (11 * 60, 22 * 60),
}


@dataclass(frozen=True)
class RhythmState:
    energy: float
    mode: str
    is_pause: bool = False
    pause_type: str = ""
    pause_seconds: float = 0.0
    routine_multipliers: dict[str, float] | None = None

    def next_interval_seconds(
        self,
        settings: dict[str, Any],
        rng: random.Random | None = None,
    ) -> float:
        rng = rng or random
        if self.is_pause:
            return max(5.0, self.pause_seconds)

        minimum = int(settings["min_interval_seconds"])
        maximum = int(settings["max_interval_seconds"])
        if minimum >= maximum:
            return float(minimum)

        mode_point = maximum - ((maximum - minimum) * self.energy)
        interval = rng.triangular(minimum, maximum, mode_point)
        if self.mode == "focus":
            interval *= 0.78
        elif self.mode == "communication":
            interval *= 0.95
        elif self.mode == "browsing":
            interval *= 1.22
        return max(float(minimum), min(float(maximum), interval))


class RhythmEngine:
    def __init__(
        self,
        rng: random.Random | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.rng = rng or random.Random()
        self.now_provider = now_provider or datetime.now
        self._plans: dict[date, dict[str, Any]] = {}
        self._mode = "focus"
        self._mode_until: datetime | None = None
        self._micro_break_until: datetime | None = None
        self._next_micro_break_at: datetime | None = None
        self._tzinfo = None

    def reset(self) -> None:
        self._plans.clear()
        self._mode = "focus"
        self._mode_until = None
        self._micro_break_until = None
        self._next_micro_break_at = None

    def evaluate(self, settings: dict[str, Any]) -> RhythmState:
        now = self.now_provider()
        self._tzinfo = now.tzinfo
        plan = self._plan_for_day(settings, now.date())
        pause_type, pause_until = self._current_pause(plan, now)
        if pause_until is None:
            pause_type, pause_until = self._current_micro_break(now)

        energy = self._energy(settings, plan, now)
        mode = self._mode_for(now, energy)
        multipliers = self._routine_multipliers(mode, energy)
        if pause_until is not None:
            return RhythmState(
                energy=energy,
                mode=mode,
                is_pause=True,
                pause_type=pause_type,
                pause_seconds=max(5.0, (pause_until - now).total_seconds()),
                routine_multipliers=multipliers,
            )
        return RhythmState(energy=energy, mode=mode, routine_multipliers=multipliers)

    def _plan_for_day(self, settings: dict[str, Any], current_day: date) -> dict[str, Any]:
        existing = self._plans.get(current_day)
        if existing is not None:
            return existing

        # Work boundaries are explicit per agent. Profile still affects energy/mode,
        # but must not redefine the configured workday.
        start_minutes = self._parse_minutes(str(settings.get("work_start", "08:30")))
        end_minutes = self._parse_minutes(str(settings.get("work_end", "18:30")))

        lunch_start = self._parse_minutes(str(settings.get("lunch_start", "12:00")))
        lunch_end = self._parse_minutes(str(settings.get("lunch_end", "13:00")))
        lunch_jitter = int(settings.get("lunch_jitter_minutes", 30))
        if lunch_jitter > 0:
            offset = self.rng.randint(-lunch_jitter, lunch_jitter)
            lunch_start += offset
            lunch_end += offset

        breaks: list[tuple[str, datetime, datetime]] = [
            (
                "lunch",
                self._at_minutes(current_day, lunch_start),
                self._at_minutes(current_day, lunch_end),
            )
        ]

        anchors = [10 * 60, 15 * 60, 16 * 60 + 30, 11 * 60]
        for anchor in anchors[: int(settings.get("coffee_break_count", 2))]:
            start = anchor + self.rng.randint(-20, 20)
            duration = self.rng.randint(5, 15)
            breaks.append(("coffee_break", self._at_minutes(current_day, start), self._at_minutes(current_day, start + duration)))

        if self.rng.random() < 0.55:
            earliest = min(end_minutes - 60, start_minutes + 150)
            latest = max(earliest, end_minutes - 90)
            start = self.rng.randint(earliest, latest)
            duration = self.rng.randint(5, 20)
            breaks.append(("long_pause", self._at_minutes(current_day, start), self._at_minutes(current_day, start + duration)))

        plan = {
            "start": self._at_minutes(current_day, start_minutes),
            "end": self._at_minutes(current_day, end_minutes),
            "lunch_start": self._at_minutes(current_day, lunch_start),
            "lunch_end": self._at_minutes(current_day, lunch_end),
            "breaks": breaks,
        }
        self._plans[current_day] = plan
        return plan

    def _current_pause(self, plan: dict[str, Any], now: datetime) -> tuple[str, datetime | None]:
        for pause_type, starts_at, ends_at in plan["breaks"]:
            if starts_at <= now < ends_at:
                return pause_type, ends_at
        return "", None

    def _current_micro_break(self, now: datetime) -> tuple[str, datetime | None]:
        if self._micro_break_until is not None and now < self._micro_break_until:
            return "micro_break", self._micro_break_until
        if self._next_micro_break_at is None or self._next_micro_break_at.date() != now.date():
            self._next_micro_break_at = now + timedelta(minutes=self.rng.randint(30, 90))
        if now >= self._next_micro_break_at:
            self._micro_break_until = now + timedelta(minutes=self.rng.randint(1, 5))
            self._next_micro_break_at = self._micro_break_until + timedelta(minutes=self.rng.randint(30, 90))
            return "micro_break", self._micro_break_until
        return "", None

    def _energy(self, settings: dict[str, Any], plan: dict[str, Any], now: datetime) -> float:
        start = plan["start"]
        end = plan["end"]
        lunch_start = plan["lunch_start"]
        lunch_end = plan["lunch_end"]
        if now < start:
            return 0.35
        if now >= end:
            return 0.25
        if start <= now < start + timedelta(hours=2):
            elapsed = (now - start).total_seconds() / 7200
            return self._clamp(0.5 + (elapsed * 0.5))
        if lunch_start - timedelta(hours=1) <= now < lunch_start:
            elapsed = (now - (lunch_start - timedelta(hours=1))).total_seconds() / 3600
            return self._clamp(0.8 - (elapsed * 0.2))
        if lunch_start <= now < lunch_end + timedelta(hours=1, minutes=30):
            elapsed = max(0.0, (now - lunch_end).total_seconds()) / 5400
            return self._clamp(0.3 + (elapsed * 0.45))

        remaining = (end - now).total_seconds()
        last_third = max(1.0, (end - start).total_seconds() / 3)
        if remaining < last_third:
            return self._clamp(0.4 + (remaining / last_third) * 0.35)
        return 0.82 if str(settings.get("profile")) != "freelancer" else 0.72

    def _mode_for(self, now: datetime, energy: float) -> str:
        if self._mode_until is not None and now < self._mode_until:
            return self._mode

        if energy >= 0.72:
            choices = ["focus", "focus", "communication", "browsing"]
            minutes = self.rng.randint(10, 30)
        elif energy <= 0.45:
            choices = ["browsing", "communication", "focus"]
            minutes = self.rng.randint(5, 14)
        else:
            choices = ["focus", "communication", "browsing"]
            minutes = self.rng.randint(7, 18)
        self._mode = self.rng.choice(choices)
        self._mode_until = now + timedelta(minutes=minutes)
        return self._mode

    def _routine_multipliers(self, mode: str, energy: float) -> dict[str, float]:
        if mode == "focus":
            return {
                "vscode_type_random_text": 1.8 + energy * 0.4,
                "scenario": 1.45,
                "open_discord": 0.45,
                "open_gmail": 0.55,
                "mouse_click": 0.85,
                "mouse_move": 0.95,
            }
        if mode == "communication":
            return {
                "vscode_type_random_text": 0.65,
                "scenario": 1.65,
                "open_discord": 1.75,
                "open_gmail": 1.55,
                "mouse_click": 0.9,
                "mouse_move": 1.15,
            }
        return {
            "vscode_type_random_text": 0.55,
            "scenario": 1.35,
            "open_discord": 0.95,
            "open_gmail": 1.2,
            "mouse_click": 1.25,
            "mouse_move": 2.1,
        }

    @staticmethod
    def _parse_minutes(value: str) -> int:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)

    def _at_minutes(self, current_day: date, minutes: int) -> datetime:
        normalized = max(0, min((24 * 60) - 1, minutes))
        return datetime.combine(
            current_day,
            dt_time(hour=normalized // 60, minute=normalized % 60),
            tzinfo=self._tzinfo,
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
