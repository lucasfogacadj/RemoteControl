import random

import pytest

from hub.control_hub.domain import SettingsError, build_command, choose_routine, default_settings, validate_settings


def test_validate_settings_requires_enabled_percentages_to_total_100():
    settings = default_settings()
    settings["routines"][0]["percentage"] = 60
    settings["routines"][1]["percentage"] = 25
    settings["routines"][2]["percentage"] = 25

    with pytest.raises(SettingsError, match="100"):
        validate_settings(settings)


def test_validate_settings_accepts_default_settings():
    settings = validate_settings(default_settings())

    assert settings["routines"][0]["id"] == "vscode_type_random_text"
    assert settings["routines"][3]["id"] == "mouse_click"
    assert settings["routines"][4]["id"] == "mouse_move"
    assert settings["routines"][5]["id"] == "scenario"
    assert settings["routines"][3]["enabled"] is False
    assert settings["code_language"] == "random"
    assert settings["typo_rate"] == 0.03
    assert settings["thinking_pause_chance"] == 0.05
    assert settings["profile"] == "developer_remote"
    assert sum(routine["percentage"] for routine in settings["routines"] if routine["enabled"]) == 100


def test_validate_settings_merges_mouse_defaults_for_legacy_payload():
    settings = default_settings()
    settings.pop("mouse_click_x")
    settings.pop("mouse_click_y")
    settings.pop("mouse_click_button")
    settings.pop("mouse_click_count")
    settings.pop("mouse_click_margin")
    settings.pop("vscode_typing_interval_seconds")
    settings.pop("typo_rate")
    settings.pop("thinking_pause_chance")
    settings.pop("code_language")
    settings["routines"] = settings["routines"][:3]

    validated = validate_settings(settings)

    mouse_routine = next(routine for routine in validated["routines"] if routine["id"] == "mouse_click")
    mouse_move_routine = next(routine for routine in validated["routines"] if routine["id"] == "mouse_move")
    scenario_routine = next(routine for routine in validated["routines"] if routine["id"] == "scenario")
    assert mouse_routine["enabled"] is False
    assert mouse_move_routine["enabled"] is False
    assert scenario_routine["enabled"] is False
    assert validated["mouse_click_button"] == "left"
    assert validated["mouse_click_count"] == 1
    assert validated["mouse_click_margin"] == 100
    assert validated["vscode_typing_interval_seconds"] == 0.08
    assert validated["typo_rate"] == 0.03
    assert validated["thinking_pause_chance"] == 0.05
    assert validated["code_language"] == "random"


def test_validate_settings_requires_vscode_file_when_enabled():
    settings = default_settings()
    settings["enabled"] = True

    with pytest.raises(SettingsError, match="Arquivo alvo"):
        validate_settings(settings)


def test_choose_routine_uses_weighted_percentages():
    settings = default_settings()
    settings["vscode_target_file"] = r"C:\Temp\control-typing.txt"
    rng = random.Random(7)
    selected = [choose_routine(settings, rng)["id"] for _ in range(200)]

    assert selected.count("vscode_type_random_text") > selected.count("open_discord")
    assert selected.count("vscode_type_random_text") > selected.count("open_gmail")


def test_validate_settings_accepts_mouse_click_settings_and_builds_command():
    settings = default_settings()
    settings["routines"][0]["percentage"] = 40
    settings["routines"][3]["enabled"] = True
    settings["routines"][3]["percentage"] = 10
    settings["mouse_click_x"] = 120
    settings["mouse_click_y"] = 240
    settings["mouse_click_button"] = "right"
    settings["mouse_click_count"] = 2
    settings["mouse_click_margin"] = 140

    validated = validate_settings(settings)
    mouse_routine = next(routine for routine in validated["routines"] if routine["id"] == "mouse_click")
    command = build_command(mouse_routine, validated)

    assert command == {
        "type": "mouse_click",
        "params": {
            "button": "right",
            "clicks": 2,
            "margin": 140,
            "move_duration_seconds": 1.2,
            "overshoot_chance": 0.15,
        },
    }


def test_build_vscode_command_includes_typing_interval():
    settings = default_settings()
    settings["vscode_typing_interval_seconds"] = 0.12
    settings["typo_rate"] = 0.04
    settings["thinking_pause_chance"] = 0.07
    settings["code_language"] = "python"

    validated = validate_settings(settings)
    routine = next(routine for routine in validated["routines"] if routine["id"] == "vscode_type_random_text")
    command = build_command(routine, validated)

    assert command["params"]["typing_interval_seconds"] == 0.12
    assert command["params"]["typo_rate"] == 0.04
    assert command["params"]["thinking_pause_chance"] == 0.07
    assert command["params"]["code_language"] == "python"


def test_build_vscode_command_scales_typing_interval_with_energy():
    settings = default_settings()
    settings["vscode_typing_interval_seconds"] = 0.1

    validated = validate_settings(settings)
    routine = next(routine for routine in validated["routines"] if routine["id"] == "vscode_type_random_text")
    high_energy = build_command(routine, validated, context={"energy": 1.0})
    low_energy = build_command(routine, validated, context={"energy": 0.0})

    assert high_energy["params"]["typing_interval_seconds"] == pytest.approx(0.075)
    assert low_energy["params"]["typing_interval_seconds"] == pytest.approx(0.125)


def test_build_mouse_move_command_includes_humanized_params():
    settings = default_settings()
    for routine in settings["routines"]:
        routine["enabled"] = routine["id"] in {"vscode_type_random_text", "mouse_move"}
        routine["percentage"] = 90 if routine["id"] == "vscode_type_random_text" else 0
    settings["routines"][4]["percentage"] = 10
    settings["mouse_move_duration_seconds"] = 2.2
    settings["mouse_overshoot_chance"] = 0.2

    validated = validate_settings(settings)
    routine = next(routine for routine in validated["routines"] if routine["id"] == "mouse_move")
    command = build_command(routine, validated)

    assert command == {
        "type": "mouse_move",
        "params": {"margin": 100, "duration_seconds": 2.2, "overshoot_chance": 0.2},
    }


def test_build_scenario_command_contains_contextual_actions():
    settings = default_settings()
    settings["scenario_type"] = "email_check"
    for routine in settings["routines"]:
        routine["enabled"] = routine["id"] in {"vscode_type_random_text", "scenario"}
        routine["percentage"] = 75 if routine["id"] == "vscode_type_random_text" else 0
    settings["routines"][5]["percentage"] = 25

    validated = validate_settings(settings)
    routine = next(routine for routine in validated["routines"] if routine["id"] == "scenario")
    command = build_command(routine, validated, context={"energy": 0.8, "mode": "communication"})

    assert command["type"] == "scenario"
    assert command["params"]["scenario_type"] == "email_check"
    assert command["params"]["mode"] == "communication"
    assert any(action["type"] == "scroll" for action in command["params"]["actions"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mouse_click_x", -1, "Coordenadas"),
        ("mouse_click_button", "side", "Botao"),
        ("mouse_click_count", 0, "Quantidade"),
        ("mouse_click_margin", 0, "Margem"),
        ("vscode_typing_interval_seconds", 3, "Intervalo de digitacao"),
        ("code_language", "php", "Linguagem de codigo"),
        ("typo_rate", 0.2, "Taxa de erro"),
        ("thinking_pause_chance", 0.4, "Chance de pausa"),
        ("mouse_move_duration_seconds", 0.1, "Duracao do movimento"),
        ("mouse_overshoot_chance", 0.5, "Chance de overshoot"),
        ("profile", "robot", "Perfil"),
        ("lunch_start", "25:00", "lunch_start"),
        ("lunch_end", "11:00", "lunch_end"),
        ("coffee_break_count", 9, "coffee breaks"),
        ("scenario_type", "anything", "Cenario"),
    ],
)
def test_validate_settings_rejects_invalid_mouse_click_settings(field, value, message):
    settings = default_settings()
    settings[field] = value

    with pytest.raises(SettingsError, match=message):
        validate_settings(settings)
