from __future__ import annotations

from copy import deepcopy
import random
from typing import Any


ROUTINE_IDS = ("vscode_type_random_text", "open_discord", "open_gmail")

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "min_interval_seconds": 60,
    "max_interval_seconds": 180,
    "vscode_target_file": "",
    "vscode_text_length": 80,
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
    ],
}


class SettingsError(ValueError):
    pass


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = default_settings()
    settings.update({key: value for key, value in payload.items() if key != "routines"})

    try:
        settings["enabled"] = bool(settings["enabled"])
        settings["min_interval_seconds"] = int(settings["min_interval_seconds"])
        settings["max_interval_seconds"] = int(settings["max_interval_seconds"])
        settings["vscode_text_length"] = int(settings["vscode_text_length"])
    except (TypeError, ValueError) as exc:
        raise SettingsError("Intervalos e tamanho de texto devem ser numeros inteiros.") from exc

    if settings["min_interval_seconds"] < 5:
        raise SettingsError("Intervalo minimo deve ser pelo menos 5 segundos.")
    if settings["max_interval_seconds"] < settings["min_interval_seconds"]:
        raise SettingsError("Intervalo maximo deve ser maior ou igual ao minimo.")
    if not 1 <= settings["vscode_text_length"] <= 500:
        raise SettingsError("Tamanho do texto do VS Code deve ficar entre 1 e 500 caracteres.")

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
    settings["routines"] = merged
    return settings


def choose_routine(settings: dict[str, Any], rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random
    validated = validate_settings(settings)
    enabled = [routine for routine in validated["routines"] if routine["enabled"] and routine["percentage"] > 0]
    if not enabled:
        raise SettingsError("Nenhuma rotina habilitada para selecao.")

    cursor = rng.uniform(0, 100)
    cumulative = 0.0
    for routine in enabled:
        cumulative += routine["percentage"]
        if cursor <= cumulative:
            return routine
    return enabled[-1]


def build_command(routine: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    routine_id = routine["id"]
    if routine_id == "vscode_type_random_text":
        return {
            "type": routine_id,
            "params": {
                "target_file": settings.get("vscode_target_file", ""),
                "text_length": settings.get("vscode_text_length", 80),
            },
        }
    if routine_id == "open_discord":
        return {"type": routine_id, "params": {}}
    if routine_id == "open_gmail":
        return {"type": routine_id, "params": {"url": "https://mail.google.com/"}}
    raise SettingsError(f"Rotina nao suportada: {routine_id}")

