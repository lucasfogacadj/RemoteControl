from __future__ import annotations

from copy import deepcopy
import math
import random
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROUTINE_IDS = (
    "vscode_type_random_text",
    "open_discord",
    "open_gmail",
    "mouse_click",
    "mouse_move",
    "scenario",
)
ROUTINE_LABELS = {
    "vscode_type_random_text": "VS Code",
    "open_discord": "Discord",
    "open_gmail": "Chrome Gmail",
    "mouse_click": "Mouse Click",
    "mouse_move": "Mouse Move",
    "scenario": "Cenario",
}
MOUSE_BUTTONS = {"left", "right", "middle"}
CODE_LANGUAGES = {"go", "python", "js", "typescript", "rust", "java", "random"}
PROFILES = {"developer_clt", "developer_remote", "freelancer"}
SCENARIO_TYPES = {"random", "coding_session", "email_check", "discord_chat"}
MAX_COMMAND_DEADLINE_SECONDS = 1800
HUB_DEADLINE_GRACE_SECONDS = 10


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "min_interval_seconds": 60,
    "max_interval_seconds": 180,
    "work_start": "08:30",
    "work_end": "18:30",
    "timezone": "America/Sao_Paulo",
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
        {"id": "vscode_type_random_text", "label": "VS Code", "enabled": True, "percentage": 50},
        {"id": "open_discord", "label": "Discord", "enabled": True, "percentage": 25},
        {"id": "open_gmail", "label": "Chrome Gmail", "enabled": True, "percentage": 25},
        {"id": "mouse_click", "label": "Mouse Click", "enabled": False, "percentage": 0},
        {"id": "mouse_move", "label": "Mouse Move", "enabled": False, "percentage": 0},
        {"id": "scenario", "label": "Cenario", "enabled": False, "percentage": 0},
    ],
}


class SettingsError(ValueError):
    pass


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def _parse_clock_minutes(value: str, field: str) -> int:
    if not isinstance(value, str):
        raise SettingsError(f"{field} deve usar o formato HH:MM.")
    parts = value.split(":")
    if len(parts) != 2:
        raise SettingsError(f"{field} deve usar o formato HH:MM.")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise SettingsError(f"{field} deve usar o formato HH:MM.") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or value != f"{hour:02d}:{minute:02d}":
        raise SettingsError(f"{field} deve usar um horario valido.")
    return hour * 60 + minute


def _strict_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsError(f"{field} deve ser booleano verdadeiro ou falso.")
    return value


def _strict_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(f"{field} deve ser um numero inteiro valido.")
    return value


def _strict_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingsError(f"{field} deve ser um numero valido.")
    result = float(value)
    if not math.isfinite(result):
        raise SettingsError(f"{field} deve ser um numero finito.")
    return result


def _strict_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SettingsError(f"{field} deve ser texto.")
    return value.strip()


def _validate_timezone(value: Any) -> str:
    timezone = _strict_string(value, "timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise SettingsError("timezone deve ser um identificador IANA valido.") from exc
    return timezone


def _validate_routines(incoming: Any) -> list[dict[str, Any]]:
    if not isinstance(incoming, list):
        raise SettingsError("Rotinas devem ser uma lista.")
    defaults_by_id = {routine["id"]: routine for routine in DEFAULT_SETTINGS["routines"]}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for routine in incoming:
        if not isinstance(routine, dict):
            raise SettingsError("Cada rotina deve ser um objeto.")
        extra = set(routine) - {"id", "label", "enabled", "percentage"}
        if extra:
            raise SettingsError(f"Campos de rotina nao permitidos: {', '.join(sorted(extra))}.")
        routine_id = routine.get("id")
        if not isinstance(routine_id, str) or routine_id not in ROUTINE_IDS:
            raise SettingsError(f"Rotina nao suportada: {routine_id}")
        if routine_id in seen:
            raise SettingsError(f"ID de rotina duplicado: {routine_id}")
        seen.add(routine_id)
        expected_label = ROUTINE_LABELS[routine_id]
        supplied_label = routine.get("label", expected_label)
        if supplied_label != expected_label:
            raise SettingsError("Labels de rotina sao controlados pelo servidor.")
        enabled = _strict_bool(routine.get("enabled", defaults_by_id[routine_id]["enabled"]), "enabled da rotina")
        percentage = _strict_int(routine.get("percentage", defaults_by_id[routine_id]["percentage"]), "percentual")
        if not 0 <= percentage <= 100:
            raise SettingsError("Cada percentual deve ficar entre 0 e 100.")
        merged.append({"id": routine_id, "label": expected_label, "enabled": enabled, "percentage": percentage})

    # Historic payloads can omit routines added in later versions. Add the canonical disabled/default rows.
    for routine_id in ROUTINE_IDS:
        if routine_id not in seen:
            merged.append(deepcopy(defaults_by_id[routine_id]))

    enabled_total = sum(item["percentage"] for item in merged if item["enabled"])
    if enabled_total != 100:
        raise SettingsError("A soma dos percentuais das rotinas habilitadas deve ser 100.")
    return merged


def validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a settings document without coercing untrusted values.

    Missing known fields are filled from defaults only to keep rows written by older hub
    versions readable during the migration. Unknown fields and unsafe scalar coercions
    are rejected, so agent-scoped API writes remain strict.
    """

    if not isinstance(payload, dict):
        raise SettingsError("Configuracao deve ser um objeto.")
    allowed = set(DEFAULT_SETTINGS)
    extras = set(payload) - allowed
    if extras:
        raise SettingsError(f"Campos de configuracao nao permitidos: {', '.join(sorted(extras))}.")

    settings = default_settings()
    for key, value in payload.items():
        if key != "routines":
            settings[key] = value

    settings["enabled"] = _strict_bool(settings["enabled"], "enabled")
    settings["min_interval_seconds"] = _strict_int(settings["min_interval_seconds"], "min_interval_seconds")
    settings["max_interval_seconds"] = _strict_int(settings["max_interval_seconds"], "max_interval_seconds")
    settings["vscode_text_length"] = _strict_int(settings["vscode_text_length"], "vscode_text_length")
    settings["vscode_typing_interval_seconds"] = _strict_float(
        settings["vscode_typing_interval_seconds"], "vscode_typing_interval_seconds"
    )
    settings["typo_rate"] = _strict_float(settings["typo_rate"], "typo_rate")
    settings["thinking_pause_chance"] = _strict_float(settings["thinking_pause_chance"], "thinking_pause_chance")
    settings["mouse_click_x"] = _strict_int(settings["mouse_click_x"], "mouse_click_x")
    settings["mouse_click_y"] = _strict_int(settings["mouse_click_y"], "mouse_click_y")
    settings["mouse_click_count"] = _strict_int(settings["mouse_click_count"], "mouse_click_count")
    settings["mouse_click_margin"] = _strict_int(settings["mouse_click_margin"], "mouse_click_margin")
    settings["mouse_move_duration_seconds"] = _strict_float(
        settings["mouse_move_duration_seconds"], "mouse_move_duration_seconds"
    )
    settings["mouse_overshoot_chance"] = _strict_float(settings["mouse_overshoot_chance"], "mouse_overshoot_chance")
    settings["lunch_jitter_minutes"] = _strict_int(settings["lunch_jitter_minutes"], "lunch_jitter_minutes")
    settings["coffee_break_count"] = _strict_int(settings["coffee_break_count"], "coffee_break_count")
    settings["work_start_jitter_minutes"] = _strict_int(
        settings["work_start_jitter_minutes"], "work_start_jitter_minutes"
    )

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
    if settings["mouse_click_x"] < 0 or settings["mouse_click_y"] < 0:
        raise SettingsError("Coordenadas do click do mouse devem ser maiores ou iguais a zero.")
    if not 1 <= settings["mouse_click_count"] <= 10:
        raise SettingsError("Quantidade de clicks do mouse deve ficar entre 1 e 10.")
    if not 1 <= settings["mouse_click_margin"] <= 1000:
        raise SettingsError("Margem segura do click do mouse deve ficar entre 1 e 1000 pixels.")
    if not 0.5 <= settings["mouse_move_duration_seconds"] <= 3.0:
        raise SettingsError("Duracao do movimento do mouse deve ficar entre 0.5 e 3 segundos.")
    if not 0 <= settings["mouse_overshoot_chance"] <= 0.3:
        raise SettingsError("Chance de overshoot do mouse deve ficar entre 0 e 0.3.")
    if not 0 <= settings["lunch_jitter_minutes"] <= 120:
        raise SettingsError("Jitter do almoco deve ficar entre 0 e 120 minutos.")
    if not 0 <= settings["coffee_break_count"] <= 4:
        raise SettingsError("Quantidade de coffee breaks deve ficar entre 0 e 4.")
    if not 0 <= settings["work_start_jitter_minutes"] <= 180:
        raise SettingsError("Jitter do inicio do trabalho deve ficar entre 0 e 180 minutos.")

    settings["vscode_target_file"] = _strict_string(settings["vscode_target_file"], "vscode_target_file")
    settings["code_language"] = _strict_string(settings["code_language"], "code_language").lower()
    if settings["code_language"] not in CODE_LANGUAGES:
        raise SettingsError("Linguagem de codigo deve ser go, python, js, typescript, rust, java ou random.")
    settings["mouse_click_button"] = _strict_string(settings["mouse_click_button"], "mouse_click_button").lower()
    if settings["mouse_click_button"] not in MOUSE_BUTTONS:
        raise SettingsError("Botao do mouse deve ser left, right ou middle.")
    settings["profile"] = _strict_string(settings["profile"], "profile").lower()
    if settings["profile"] not in PROFILES:
        raise SettingsError("Perfil deve ser developer_clt, developer_remote ou freelancer.")
    settings["scenario_type"] = _strict_string(settings["scenario_type"], "scenario_type").lower()
    if settings["scenario_type"] not in SCENARIO_TYPES:
        raise SettingsError("Cenario deve ser random, coding_session, email_check ou discord_chat.")

    settings["lunch_start"] = _strict_string(settings["lunch_start"], "lunch_start")
    settings["lunch_end"] = _strict_string(settings["lunch_end"], "lunch_end")
    lunch_start = _parse_clock_minutes(settings["lunch_start"], "lunch_start")
    lunch_end = _parse_clock_minutes(settings["lunch_end"], "lunch_end")
    if lunch_end <= lunch_start:
        raise SettingsError("lunch_end deve ser depois de lunch_start.")

    settings["work_start"] = _strict_string(settings["work_start"], "work_start")
    settings["work_end"] = _strict_string(settings["work_end"], "work_end")
    work_start = _parse_clock_minutes(settings["work_start"], "work_start")
    work_end = _parse_clock_minutes(settings["work_end"], "work_end")
    if work_end <= work_start:
        raise SettingsError("work_end deve ser depois de work_start; janelas atravessando meia-noite nao sao suportadas.")
    settings["timezone"] = _validate_timezone(settings["timezone"])

    settings["routines"] = _validate_routines(payload.get("routines", DEFAULT_SETTINGS["routines"]))
    vscode_enabled = any(
        item["id"] == "vscode_type_random_text" and item["enabled"] and item["percentage"] > 0
        for item in settings["routines"]
    )
    coding_scenario_enabled = any(
        item["id"] == "scenario" and item["enabled"] and item["percentage"] > 0
        for item in settings["routines"]
    ) and settings["scenario_type"] in {"random", "coding_session"}
    if settings["enabled"] and (vscode_enabled or coding_scenario_enabled) and not settings["vscode_target_file"]:
        raise SettingsError("Arquivo alvo do VS Code deve ser configurado quando a rotina VS Code estiver ativa.")

    if worst_case_deadline_seconds(settings) > MAX_COMMAND_DEADLINE_SECONDS:
        raise SettingsError("A configuracao pode exceder o teto de 1800 segundos por comando.")
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
        if isinstance(energy, (int, float)) and not isinstance(energy, bool):
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


def estimate_command_seconds(command: dict[str, Any]) -> float:
    """Return a conservative bounded execution estimate for a declarative command."""

    command_type = command.get("type")
    params = command.get("params") if isinstance(command.get("params"), dict) else {}
    if command_type == "vscode_type_random_text":
        text_length = params.get("text_length", 80)
        interval = params.get("typing_interval_seconds", 0.08)
        if isinstance(text_length, bool) or not isinstance(text_length, int):
            return float(MAX_COMMAND_DEADLINE_SECONDS)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(float(interval)):
            return float(MAX_COMMAND_DEADLINE_SECONDS)
        # Typing, occasional correction/thinking pauses, focus/opening margin.
        return max(5.0, min(1200.0, text_length * max(0.02, float(interval)) * 2.5 + 25.0))
    if command_type in {"open_discord", "open_gmail"}:
        return 20.0
    if command_type == "mouse_click":
        return max(5.0, min(90.0, float(params.get("move_duration_seconds", 1.2)) * 3 + 10.0))
    if command_type == "mouse_move":
        return max(5.0, min(90.0, float(params.get("duration_seconds", 1.2)) * 3 + 10.0))
    if command_type == "scenario":
        actions = params.get("actions") if isinstance(params.get("actions"), list) else []
        total = 15.0
        for action in actions:
            if not isinstance(action, dict):
                return float(MAX_COMMAND_DEADLINE_SECONDS)
            if action.get("type") == "wait":
                seconds = action.get("seconds", action.get("max_seconds", 0))
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(float(seconds)):
                    return float(MAX_COMMAND_DEADLINE_SECONDS)
                total += max(0.0, float(seconds))
            elif action.get("type") in {"type_text", "type_code"}:
                total += 120.0
            else:
                total += 15.0
        return min(1200.0, total)
    return float(MAX_COMMAND_DEADLINE_SECONDS)


def command_budgets(command: dict[str, Any]) -> tuple[int, int]:
    estimate = estimate_command_seconds(command)
    execution_budget = math.ceil(estimate * 1.5 + 15)
    deadline_budget = execution_budget + HUB_DEADLINE_GRACE_SECONDS
    return execution_budget, deadline_budget


def worst_case_deadline_seconds(settings: dict[str, Any]) -> int:
    validated_like = settings
    worst = 0
    for routine in validated_like.get("routines", []):
        if routine.get("enabled") and routine.get("percentage", 0) > 0:
            _, deadline = command_budgets(build_command(routine, validated_like))
            worst = max(worst, deadline)
    return worst or command_budgets({"type": "open_gmail", "params": {}})[1]
