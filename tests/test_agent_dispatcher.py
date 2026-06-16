import asyncio
import random
import sys
from types import SimpleNamespace

from windows_agent.agent import AgentConfig, dispatch_command, random_go_code, random_mouse_point, resolve_executable


def config(**overrides):
    values = {
        "hub_ws_url": "ws://localhost:8080/ws/agent",
        "pairing_token": "token",
        "agent_id": "test-agent",
        "dry_run": True,
        "heartbeat_seconds": 10,
        "vscode_executable": "code",
        "vscode_target_file": "",
        "discord_executable": "",
        "chrome_executable": "chrome",
    }
    values.update(overrides)
    return AgentConfig(**values)


def test_dispatch_rejects_unsupported_command():
    response = asyncio.run(dispatch_command({"id": "1", "type": "run_anything"}, config()))

    assert response["status"] == "failure"
    assert "nao suportado" in response["message"]


def test_vscode_requires_target_file():
    response = asyncio.run(dispatch_command({"id": "1", "type": "vscode_type_random_text", "params": {}}, config()))

    assert response["status"] == "failure"
    assert "Arquivo alvo" in response["message"]


def test_vscode_reports_missing_target_parent_when_active(tmp_path):
    missing_file = tmp_path / "missing" / "target.txt"

    response = asyncio.run(
        dispatch_command(
            {"id": "1", "type": "vscode_type_random_text", "params": {"target_file": str(missing_file)}},
            config(dry_run=False, vscode_executable=""),
        )
    )

    assert response["status"] == "failure"
    assert "Pasta do arquivo alvo" in response["message"]


def test_gmail_dry_run_succeeds_without_opening_browser():
    response = asyncio.run(dispatch_command({"id": "1", "type": "open_gmail", "params": {}}, config()))

    assert response["status"] == "success"
    assert "Dry-run" in response["message"]


def test_mouse_click_dry_run_succeeds_without_clicking():
    response = asyncio.run(
        dispatch_command(
            {"id": "1", "type": "mouse_click", "params": {"button": "left", "clicks": 2, "margin": 80}},
            config(),
        )
    )

    assert response["status"] == "success"
    assert "Dry-run Mouse" in response["message"]
    assert "aleatorio" in response["message"]


def test_mouse_click_rejects_invalid_button():
    response = asyncio.run(
        dispatch_command(
            {"id": "1", "type": "mouse_click", "params": {"button": "side", "clicks": 1, "margin": 80}},
            config(),
        )
    )

    assert response["status"] == "failure"
    assert "Botao" in response["message"]


def test_random_mouse_point_uses_safe_margin():
    fake_pyautogui = SimpleNamespace(size=lambda: (1920, 1080))

    x, y = random_mouse_point(fake_pyautogui, 120, random.Random(4))

    assert 120 <= x <= 1799
    assert 120 <= y <= 959


def test_mouse_click_active_uses_random_safe_point(monkeypatch):
    class FailSafeException(Exception):
        pass

    captured = {}

    def click(**kwargs):
        captured.update(kwargs)

    fake_pyautogui = SimpleNamespace(
        FailSafeException=FailSafeException,
        click=click,
        size=lambda: (1920, 1080),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    response = asyncio.run(
        dispatch_command(
            {"id": "1", "type": "mouse_click", "params": {"x": 0, "y": 0, "button": "left", "clicks": 1, "margin": 100}},
            config(dry_run=False),
        )
    )

    assert response["status"] == "success"
    assert 100 <= captured["x"] <= 1819
    assert 100 <= captured["y"] <= 979
    assert captured["button"] == "left"


def test_mouse_click_reports_failsafe_exception_when_cursor_is_in_corner(monkeypatch):
    class FailSafeException(Exception):
        pass

    def click(**_kwargs):
        raise FailSafeException()

    fake_pyautogui = SimpleNamespace(
        FailSafeException=FailSafeException,
        click=click,
        size=lambda: (1920, 1080),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    response = asyncio.run(
        dispatch_command(
            {"id": "1", "type": "mouse_click", "params": {"button": "left", "clicks": 1, "margin": 100}},
            config(dry_run=False),
        )
    )

    assert response["status"] == "failure"
    assert "Mova o mouse" in response["message"]


def test_random_go_code_generates_go_snippet():
    code = random_go_code(80)

    assert "package main" in code
    assert "func main()" in code
    assert "fmt." in code
    assert code.count("package main") == 1


def test_resolve_executable_accepts_existing_explicit_path(tmp_path):
    executable = tmp_path / "tool.exe"
    executable.write_text("", encoding="utf-8")

    assert resolve_executable(str(executable), []) == str(executable)


def test_resolve_executable_uses_common_paths(tmp_path, monkeypatch):
    root = tmp_path / "Programs"
    executable = root / "App" / "tool.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(root))

    assert resolve_executable("", [r"%LocalAppData%\App\tool.exe"]) == str(executable)
