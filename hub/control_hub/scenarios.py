from __future__ import annotations

import random
from typing import Any


SCENARIO_TYPES = ("coding_session", "email_check", "discord_chat")


def _choose_scenario(settings: dict[str, Any], rng: random.Random) -> str:
    requested = str(settings.get("scenario_type", "random")).strip().lower()
    if requested in SCENARIO_TYPES:
        return requested
    return rng.choices(
        list(SCENARIO_TYPES),
        weights=[0.55, 0.22, 0.23],
        k=1,
    )[0]


def _wait(min_seconds: float, max_seconds: float) -> dict[str, Any]:
    return {"type": "wait", "min_seconds": min_seconds, "max_seconds": max_seconds}


def _mouse_move(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "mouse_move",
        "duration_seconds": settings.get("mouse_move_duration_seconds", 1.2),
        "margin": settings.get("mouse_click_margin", 100),
        "overshoot_chance": settings.get("mouse_overshoot_chance", 0.15),
    }


def _scroll(direction: str, bursts: int = 2) -> dict[str, Any]:
    return {"type": "scroll", "direction": direction, "bursts": bursts}


def _hotkey(*keys: str) -> dict[str, Any]:
    return {"type": "hotkey", "keys": list(keys)}


def _click(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "mouse_click",
        "button": settings.get("mouse_click_button", "left"),
        "clicks": 1,
        "margin": settings.get("mouse_click_margin", 100),
        "move_duration_seconds": settings.get("mouse_move_duration_seconds", 1.2),
        "overshoot_chance": settings.get("mouse_overshoot_chance", 0.15),
    }


def _code_text(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "type_text",
        "text_kind": "code",
        "text_length": settings.get("vscode_text_length", 80),
        "typing_interval_seconds": settings.get("vscode_typing_interval_seconds", 0.08),
        "typo_rate": settings.get("typo_rate", 0.03),
        "thinking_pause_chance": settings.get("thinking_pause_chance", 0.05),
        "code_language": settings.get("code_language", "random"),
    }


def _natural_text(text: str, settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "type_text",
        "text": text,
        "typing_interval_seconds": settings.get("vscode_typing_interval_seconds", 0.08),
        "typo_rate": min(0.02, float(settings.get("typo_rate", 0.03))),
        "thinking_pause_chance": min(0.04, float(settings.get("thinking_pause_chance", 0.05))),
    }


def _coding_session(settings: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    shortcut_pool = [
        _hotkey("ctrl", "p"),
        _hotkey("ctrl", "shift", "e"),
        _hotkey("ctrl", "/"),
        _hotkey("ctrl", "d"),
        _hotkey("ctrl", "shift", "k"),
        _hotkey("ctrl", "z"),
    ]
    shortcuts = rng.sample(shortcut_pool, k=rng.randint(1, 3))
    actions: list[dict[str, Any]] = [
        {"type": "open_app", "app": "vscode", "target_file": settings.get("vscode_target_file", "")},
        _mouse_move(settings),
        _scroll(rng.choice(["down", "down", "up"]), bursts=rng.randint(1, 2)),
        _wait(2, 5),
    ]
    actions.extend(shortcuts)
    if rng.random() < 0.65:
        actions.append(_hotkey("shift", "down"))
    actions.append(_code_text(settings))
    actions.append(_hotkey("ctrl", "s"))
    if rng.random() < 0.35:
        actions.extend(
            [
                _wait(0.8, 2.0),
                _hotkey("ctrl", "`"),
                _natural_text(rng.choice(["pytest -q", "go test ./...", "npm test -- --runInBand"]), settings),
                _wait(1.0, 2.5),
                _hotkey("ctrl", "`"),
            ]
        )
    return actions


def _email_check(settings: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    actions = [
        {"type": "alt_tab"} if rng.random() < 0.35 else _wait(0.2, 0.8),
        {"type": "open_app", "app": "gmail", "url": "https://mail.google.com/"},
        _wait(5, 15),
        _scroll("down", bursts=rng.randint(1, 3)),
        _mouse_move(settings),
        _click(settings),
        _wait(10, 30),
    ]
    if rng.random() < 0.6:
        actions.append(_hotkey("alt", "left"))
    return actions


def _discord_chat(settings: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    messages = [
        "dei uma olhada aqui",
        "vou validar e ja retorno",
        "faz sentido pra mim",
        "subi um ajuste pequeno",
    ]
    actions = [
        {"type": "alt_tab"} if rng.random() < 0.35 else _wait(0.2, 0.8),
        {"type": "open_app", "app": "discord"},
        _scroll(rng.choice(["down", "down", "up"]), bursts=rng.randint(1, 2)),
        _wait(3, 10),
        _mouse_move(settings),
        _click(settings),
    ]
    if rng.random() < 0.35:
        actions.append(_natural_text(rng.choice(messages), settings))
    actions.append(_wait(1.5, 4.0))
    return actions


def build_scenario_command(
    settings: dict[str, Any],
    context: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    rng = rng or random
    context = context or {}
    scenario_type = _choose_scenario(settings, rng)
    builders = {
        "coding_session": _coding_session,
        "email_check": _email_check,
        "discord_chat": _discord_chat,
    }
    actions = builders[scenario_type](settings, rng)
    return {
        "type": "scenario",
        "params": {
            "scenario_type": scenario_type,
            "mode": context.get("mode", ""),
            "energy": context.get("energy"),
            "actions": actions,
        },
    }
