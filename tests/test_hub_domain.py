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
    assert settings["routines"][3]["enabled"] is False
    assert sum(routine["percentage"] for routine in settings["routines"] if routine["enabled"]) == 100


def test_validate_settings_merges_mouse_defaults_for_legacy_payload():
    settings = default_settings()
    settings.pop("mouse_click_x")
    settings.pop("mouse_click_y")
    settings.pop("mouse_click_button")
    settings.pop("mouse_click_count")
    settings.pop("mouse_click_margin")
    settings.pop("vscode_typing_interval_seconds")
    settings["routines"] = settings["routines"][:3]

    validated = validate_settings(settings)

    mouse_routine = next(routine for routine in validated["routines"] if routine["id"] == "mouse_click")
    assert mouse_routine["enabled"] is False
    assert validated["mouse_click_button"] == "left"
    assert validated["mouse_click_count"] == 1
    assert validated["mouse_click_margin"] == 100
    assert validated["vscode_typing_interval_seconds"] == 0.08


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
        "params": {"button": "right", "clicks": 2, "margin": 140},
    }


def test_build_vscode_command_includes_typing_interval():
    settings = default_settings()
    settings["vscode_typing_interval_seconds"] = 0.12

    validated = validate_settings(settings)
    routine = next(routine for routine in validated["routines"] if routine["id"] == "vscode_type_random_text")
    command = build_command(routine, validated)

    assert command["params"]["typing_interval_seconds"] == 0.12


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mouse_click_x", -1, "Coordenadas"),
        ("mouse_click_button", "side", "Botao"),
        ("mouse_click_count", 0, "Quantidade"),
        ("mouse_click_margin", 0, "Margem"),
        ("vscode_typing_interval_seconds", 3, "Intervalo de digitacao"),
    ],
)
def test_validate_settings_rejects_invalid_mouse_click_settings(field, value, message):
    settings = default_settings()
    settings[field] = value

    with pytest.raises(SettingsError, match=message):
        validate_settings(settings)
