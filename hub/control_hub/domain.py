from __future__ import annotations

from copy import deepcopy
import random
from typing import Any


ROUTINE_IDS = (
    "vscode_type_random_text",
    "open_discord",
    "open_gmail",
    "mouse_click",
    "mouse_move",
    "scenario",
)
MOUSE_BUTTONS = {"left", "right", "middle"}
CODE_LANGUAGES = {"go", "python", "js", "typescript", "rust", "java", "random"}
PROFILES = {"developer_clt", "developer_remote", "freelancer"}
SCENARIO_TYPES = {"random", "coding_session", "email_check", "discord_chat"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "min_interval_seconds": 60,
    "max_interval_seconds": 180,
    "vscode_target_file": "",
    "vscode_text_length": 80,
    "vscode_typing_interval_seconds": 0.08,
    "typo_rate": 0.03,
    "thinking_pause_chance": 0.05,
    "code_language": "random",
    "mouse_click_x": 0,
    "mouse_click_y": 0,
    "mouse_click_button": "left",
    "mouse_click_count": 1,
    "mouse_click_margin": 100,
    "mouse_move_duration_seconds": 1.2,
    "mouse_overshoot_chance": 0.15,
    "profile": "developer_remote",
    "lunch_start": "12:00",
    "lunch_end": "13:00",
    "lunch_jitter_minutes": 30,
    "coffee_break_count": 2,
    "work_start_jitter_minutes": 30,
    "scenario_type": "random",
    "routines": [
        {
            "id": "vscode_type_random_text",
            "label": "VS Code",
            "enabled": True,
            "percentage": 50,
        },
        {
            "id": "open_discord",
            "label": "Discord",
            "enabled": True,
            "percentage": 25,
        },
        {
            "id": "open_gmail",
            "label": "Chrome Gmail",
            "enabled": True,
            "percentage": 25,
        },
        {
            "id": "mouse_click",
            "label": "Mouse Click",
            "enabled": False,
            "percentage": 0,
        },
        {
            "id": "mouse_move",
            "label": "Mouse Move",
            "enabled": False,
            "percentage": 0,
        },
        {
            "id": "scenario",
            "label": "Cenario",
            "enabled": False,
            "percentage": 0,
        },
    ],
}


class SettingsError(ValueError):
    pass


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def _parse_clock_minutes(value: str, field: str) -> int:
    parts = value.split(":")
    if len(parts) != 2:
        raise SettingsError(f"{field} deve usar o formato HH:MM.")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise SettingsError(f"{field} deve usar o formato HH:MM.") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise SettingsError(f"{field} deve usar um horario valido.")
    return hour * 60 + minute


def validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = default_settings()
    settings.update({key: value for key, value in payload.items() if key != "routines"})

    try:
        settings["enabled"] = bool(settings["enabled"])
        settings["min_interval_seconds"] = int(settings["min_interval_seconds"])
        settings["max_interval_seconds"] = int(settings["max_interval_seconds"])
        settings["vscode_text_length"] = int(settings["vscode_text_length"])
        settings["vscode_typing_interval_seconds"] = float(settings["vscode_typing_interval_seconds"])
        settings["typo_rate"] = float(settings["typo_rate"])
        settings["thinking_pause_chance"] = float(settings["thinking_pause_chance"])
        settings["mouse_click_x"] = int(settings["mouse_click_x"])
        settings["mouse_click_y"] = int(settings["mouse_click_y"])
        settings["mouse_click_count"] = int(settings["mouse_click_count"])
        settings["mouse_click_margin"] = int(settings["mouse_click_margin"])
        settings["mouse_move_duration_seconds"] = float(settings["mouse_move_duration_seconds"])
        settings["mouse_overshoot_chance"] = float(settings["mouse_overshoot_chance"])
        settings["lunch_jitter_minutes"] = int(settings["lunch_jitter_minutes"])
        settings["coffee_break_count"] = int(settings["coffee_break_count"])
        settings["work_start_jitter_minutes"] = int(settings["work_start_jitter_minutes"])
    except (TypeError, ValueError) as exc:
        raise SettingsError("Intervalos, texto e parametros de mouse devem ser numeros validos.") from exc

    if settings["min_interval_seconds"] < 5:
        raise SettingsError("Intervalo minimo deve ser pelo menos 5 segundos.")
    if settings["max_interval_seconds"] < settings["min_interval_seconds"]:
        raise SettingsError("Intervalo maximo deve ser maior ou igual ao minimo.")
    if not 1 <= settings["vscode_text_length"] <= 500:
        raise SettingsError("Tamanho do texto do VS Code deve ficar entre 1 e 500 caracteres.")
    if not 0 <= settings["vscode_typing_interval_seconds"] <= 2:
        raise SettingsError("Intervalo de digitacao do VS Code deve ficar entre 0 e 2 segundos.")
    if not 0 <= settings["typo_rate"] <= 0.1:
        raise SettingsError("Taxa de erro de digitacao deve ficar entre 0 e 0.1.")
    if not 0 <= settings["thinking_pause_chance"] <= 0.2:
        raise SettingsError("Chance de pausa de pensamento deve ficar entre 0 e 0.2.")
    settings["code_language"] = str(settings.get("code_language", "")).strip().lower()
    if settings["code_language"] not in CODE_LANGUAGES:
        raise SettingsError("Linguagem de codigo deve ser go, python, js, typescript, rust, java ou random.")
    settings["mouse_click_button"] = str(settings.get("mouse_click_button", "")).strip().lower()
    if settings["mouse_click_x"] < 0 or settings["mouse_click_y"] < 0:
        raise SettingsError("Coordenadas do click do mouse devem ser maiores ou iguais a zero.")
    if settings["mouse_click_button"] not in MOUSE_BUTTONS:
        raise SettingsError("Botao do mouse deve ser left, right ou middle.")
    if not 1 <= settings["mouse_click_count"] <= 10:
        raise SettingsError("Quantidade de clicks do mouse deve ficar entre 1 e 10.")
    if not 1 <= settings["mouse_click_margin"] <= 1000:
        raise SettingsError("Margem segura do click do mouse deve ficar entre 1 e 1000 pixels.")
    if not 0.5 <= settings["mouse_move_duration_seconds"] <= 3.0:
        raise SettingsError("Duracao do movimento do mouse deve ficar entre 0.5 e 3 segundos.")
    if not 0 <= settings["mouse_overshoot_chance"] <= 0.3:
        raise SettingsError("Chance de overshoot do mouse deve ficar entre 0 e 0.3.")
    settings["profile"] = str(settings.get("profile", "")).strip().lower()
    if settings["profile"] not in PROFILES:
        raise SettingsError("Perfil deve ser developer_clt, developer_remote ou freelancer.")
    settings["lunch_start"] = str(settings.get("lunch_start", "")).strip()
    settings["lunch_end"] = str(settings.get("lunch_end", "")).strip()
    lunch_start = _parse_clock_minutes(settings["lunch_start"], "lunch_start")
    lunch_end = _parse_clock_minutes(settings["lunch_end"], "lunch_end")
    if lunch_end <= lunch_start:
        raise SettingsError("lunch_end deve ser depois de lunch_start.")
    if not 0 <= settings["lunch_jitter_minutes"] <= 120:
        raise SettingsError("Jitter do almoco deve ficar entre 0 e 120 minutos.")
    if not 0 <= settings["coffee_break_count"] <= 4:
        raise SettingsError("Quantidade de coffee breaks deve ficar entre 0 e 4.")
    if not 0 <= settings["work_start_jitter_minutes"] <= 180:
        raise SettingsError("Jitter do inicio do trabalho deve ficar entre 0 e 180 minutos.")
    settings["scenario_type"] = str(settings.get("scenario_type", "")).strip().lower()
    if settings["scenario_type"] not in SCENARIO_TYPES:
        raise SettingsError("Cenario deve ser random, coding_session, email_check ou discord_chat.")

    incoming_routines = payload.get("routines", DEFAULT_SETTINGS["routines"])
    if not isinstance(incoming_routines, list):
        raise SettingsError("Rotinas devem ser uma lista.")

    defaults_by_id = {routine["id"]: routine for routine in DEFAULT_SETTINGS["routines"]}
    merged: list[dict[str, Any]] = []
    seen = set()
    for routine in incoming_routines:
        if not isinstance(routine, dict):
            raise SettingsError("Cada rotina deve ser um objeto.")
        routine_id = str(routine.get("id", ""))
        if routine_id not in ROUTINE_IDS:
            raise SettingsError(f"Rotina nao suportada: {routine_id}")
        seen.add(routine_id)
        item = deepcopy(defaults_by_id[routine_id])
        item.update(routine)
        item["enabled"] = bool(item.get("enabled", True))
        try:
            item["percentage"] = int(item.get("percentage", 0))
        except (TypeError, ValueError) as exc:
            raise SettingsError("Percentuais devem ser numeros inteiros.") from exc
        if not 0 <= item["percentage"] <= 100:
            raise SettingsError("Cada percentual deve ficar entre 0 e 100.")
        merged.append(item)

    for routine_id in ROUTINE_IDS:
        if routine_id not in seen:
            merged.append(deepcopy(defaults_by_id[routine_id]))

    enabled_total = sum(item["percentage"] for item in merged if item["enabled"])
    if enabled_total != 100:
        raise SettingsError("A soma dos percentuais das rotinas habilitadas deve ser 100.")

    settings["vscode_target_file"] = str(settings.get("vscode_target_file", "")).strip()
    vscode_enabled = any(
        item["id"] == "vscode_type_random_text" and item["enabled"] and item["percentage"] > 0
        for item in merged
    )
    coding_scenario_enabled = any(
        item["id"] == "scenario" and item["enabled"] and item["percentage"] > 0
        for item in merged
    ) and settings["scenario_type"] in {"random", "coding_session"}
    if settings["enabled"] and (vscode_enabled or coding_scenario_enabled) and not settings["vscode_target_file"]:
        raise SettingsError("Arquivo alvo do VS Code deve ser configurado quando a rotina VS Code estiver ativa.")

    settings["routines"] = merged
    return settings


def choose_routine(
    settings: dict[str, Any],
    rng: random.Random | None = None,
    routine_multipliers: dict[str, float] | None = None,
) -> dict[str, Any]:
    rng = rng or random
    validated = validate_settings(settings)
    enabled = [routine for routine in validated["routines"] if routine["enabled"] and routine["percentage"] > 0]
    if not enabled:
        raise SettingsError("Nenhuma rotina habilitada para selecao.")

    routine_multipliers = routine_multipliers or {}
    weighted = [
        (routine, max(0.0, float(routine["percentage"]) * routine_multipliers.get(routine["id"], 1.0)))
        for routine in enabled
    ]
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        raise SettingsError("Nenhuma rotina habilitada para selecao.")

    cursor = rng.uniform(0, total)
    cumulative = 0.0
    for routine, weight in weighted:
        cumulative += weight
        if cursor <= cumulative:
            return routine
    return enabled[-1]


def build_command(
    routine: dict[str, Any],
    settings: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    routine_id = routine["id"]
    context = context or {}
    if routine_id == "vscode_type_random_text":
        typing_interval = float(settings.get("vscode_typing_interval_seconds", 0.08))
        energy = context.get("energy")
        if isinstance(energy, (int, float)):
            typing_interval *= 1.25 - (max(0.0, min(1.0, float(energy))) * 0.5)
        return {
            "type": routine_id,
            "params": {
                "target_file": settings.get("vscode_target_file", ""),
                "text_length": settings.get("vscode_text_length", 80),
                "typing_interval_seconds": max(0.0, min(2.0, typing_interval)),
                "typo_rate": settings.get("typo_rate", 0.03),
                "thinking_pause_chance": settings.get("thinking_pause_chance", 0.05),
                "code_language": settings.get("code_language", "random"),
            },
        }
    if routine_id == "open_discord":
        return {"type": routine_id, "params": {}}
    if routine_id == "open_gmail":
        return {"type": routine_id, "params": {"url": "https://mail.google.com/"}}
    if routine_id == "mouse_click":
        return {
            "type": routine_id,
            "params": {
                "button": settings.get("mouse_click_button", "left"),
                "clicks": settings.get("mouse_click_count", 1),
                "margin": settings.get("mouse_click_margin", 100),
                "move_duration_seconds": settings.get("mouse_move_duration_seconds", 1.2),
                "overshoot_chance": settings.get("mouse_overshoot_chance", 0.15),
            },
        }
    if routine_id == "mouse_move":
        return {
            "type": routine_id,
            "params": {
                "margin": settings.get("mouse_click_margin", 100),
                "duration_seconds": settings.get("mouse_move_duration_seconds", 1.2),
                "overshoot_chance": settings.get("mouse_overshoot_chance", 0.15),
            },
        }
    if routine_id == "scenario":
        from .scenarios import build_scenario_command

        return build_scenario_command(settings, context=context)
    raise SettingsError(f"Rotina nao suportada: {routine_id}")
