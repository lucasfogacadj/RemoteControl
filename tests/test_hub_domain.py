import random

import pytest

from hub.control_hub.domain import SettingsError, choose_routine, default_settings, validate_settings


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
    assert sum(routine["percentage"] for routine in settings["routines"] if routine["enabled"]) == 100


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
