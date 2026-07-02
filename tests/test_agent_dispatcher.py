import asyncio
import json
import os
import random
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import windows_agent.agent as agent_module
from windows_agent.agent import (
    AgentConfig,
    COMMAND_CANCELLED_MESSAGE,
    COMMAND_BUSY_MESSAGE,
    CommandCancelled,
    command_loop,
    dispatch_command,
    dispatch_command_in_worker,
    dispatch_command_with_timeout,
    env_optional_float,
    load_env_file,
    load_config,
    random_go_code,
    random_mouse_point,
    resolve_executable,
    run_connection,
    type_text,
)


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
        "reconnect_seconds": 5,
        "websocket_ping_interval_seconds": None,
        "websocket_ping_timeout_seconds": None,
        "command_timeout_seconds": 120,
        "sentry_dsn": "",
        "sentry_environment": "production",
        "sentry_release": "",
        "sentry_traces_sample_rate": 0.0,
        "sentry_send_default_pii": False,
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


def test_type_text_yields_between_characters():
    delays = []
    pressed = []
    written = []

    class FakePyAutoGUI:
        def press(self, key):
            pressed.append(key)

        def write(self, character, interval=0):
            written.append((character, interval))

    async def fake_sleep(delay):
        delays.append(delay)

    asyncio.run(type_text(FakePyAutoGUI(), "a\nb", 0.25, sleep=fake_sleep))

    assert pressed == ["enter"]
    assert written == [("a", 0), ("b", 0)]
    assert delays == [0.25, 0.25]


def test_type_text_stops_when_cancelled():
    cancel_event = threading.Event()
    written = []

    class FakePyAutoGUI:
        def press(self, key):
            raise AssertionError(f"unexpected key press: {key}")

        def write(self, character, interval=0):
            written.append((character, interval))

    async def fake_sleep(_delay):
        cancel_event.set()

    with pytest.raises(CommandCancelled):
        asyncio.run(type_text(FakePyAutoGUI(), "abc", 0.25, cancel_event=cancel_event, sleep=fake_sleep))

    assert written == [("a", 0)]


def test_dispatch_command_returns_cancelled_when_cancel_event_is_set():
    cancel_event = threading.Event()
    cancel_event.set()

    response = asyncio.run(dispatch_command({"id": "1", "type": "open_gmail", "params": {}}, config(), cancel_event))

    assert response == {
        "type": "result",
        "command_id": "1",
        "routine": "open_gmail",
        "status": "cancelled",
        "message": COMMAND_CANCELLED_MESSAGE,
    }


def test_run_connection_exits_when_heartbeat_send_fails():
    class BrokenWebSocket:
        async def send(self, _payload):
            raise RuntimeError("connection lost")

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(10)
            return "{}"

    async def run():
        with pytest.raises(RuntimeError, match="connection lost"):
            await asyncio.wait_for(run_connection(BrokenWebSocket(), config(heartbeat_seconds=1)), timeout=1)

    asyncio.run(run())


def test_dispatch_command_in_worker_keeps_event_loop_responsive(monkeypatch):
    async def slow_dispatch(command, _config, _cancel_event=None):
        time.sleep(0.2)
        return {"type": "result", "command_id": command["id"], "status": "success", "message": "done"}

    monkeypatch.setattr(agent_module, "dispatch_command", slow_dispatch)

    async def run():
        task = asyncio.create_task(dispatch_command_in_worker({"id": "1"}, config()))
        await asyncio.sleep(0.02)

        start = time.perf_counter()
        await asyncio.sleep(0.02)

        assert time.perf_counter() - start < 0.1
        assert not task.done()
        assert (await task)["status"] == "success"

    asyncio.run(run())


def test_dispatch_command_with_timeout_reports_failure(monkeypatch):
    async def slow_dispatch(command, _config, _cancel_event=None):
        await asyncio.sleep(0.2)
        return {"type": "result", "command_id": command["id"], "status": "success", "message": "done"}

    monkeypatch.setattr(agent_module, "dispatch_command", slow_dispatch)

    response = asyncio.run(dispatch_command_with_timeout({"id": "1", "type": "vscode_type_random_text"}, config(command_timeout_seconds=0.05)))

    assert response == {
        "type": "result",
        "command_id": "1",
        "routine": "vscode_type_random_text",
        "status": "failure",
        "message": "Comando excedeu o tempo limite de 0.05s.",
    }


def test_command_loop_rejects_new_command_while_worker_is_busy(monkeypatch):
    async def slow_dispatch(command, _config, _cancel_event=None):
        time.sleep(0.2)
        return {"type": "result", "command_id": command["id"], "status": "success", "message": "done"}

    class TwoCommandWebSocket:
        def __init__(self):
            self.sent = []
            self._messages = [
                {"type": "command", "command": {"id": "1", "type": "vscode_type_random_text"}},
                {"type": "command", "command": {"id": "2", "type": "vscode_type_random_text"}},
            ]
            self._index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._index >= len(self._messages):
                raise StopAsyncIteration
            message = self._messages[self._index]
            self._index += 1
            if self._index == 2:
                await asyncio.sleep(0.02)
            return json.dumps(message)

        async def send(self, payload):
            self.sent.append(json.loads(payload))

    monkeypatch.setattr(agent_module, "dispatch_command", slow_dispatch)
    websocket = TwoCommandWebSocket()

    asyncio.run(command_loop(websocket, config()))

    assert websocket.sent == [
        {
            "type": "result",
            "command_id": "2",
            "routine": "vscode_type_random_text",
            "status": "failure",
            "message": COMMAND_BUSY_MESSAGE,
        }
    ]


def test_command_loop_accepts_cancel_control_while_worker_is_busy(monkeypatch):
    async def wait_for_cancel(command, _config, cancel_event=None):
        while cancel_event is None or not cancel_event.is_set():
            await asyncio.sleep(0.005)
        return {
            "type": "result",
            "command_id": command["id"],
            "routine": command["type"],
            "status": "cancelled",
            "message": COMMAND_CANCELLED_MESSAGE,
        }

    class CancelCommandWebSocket:
        def __init__(self):
            self.sent = []
            self._messages = [
                {"type": "command", "command": {"id": "1", "type": "vscode_type_random_text"}},
                {"type": "control", "action": "cancel_active_command"},
            ]
            self._index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._index >= len(self._messages):
                await asyncio.sleep(0.08)
                raise StopAsyncIteration
            message = self._messages[self._index]
            self._index += 1
            if self._index == 2:
                await asyncio.sleep(0.02)
            return json.dumps(message)

        async def send(self, payload):
            self.sent.append(json.loads(payload))

    monkeypatch.setattr(agent_module, "dispatch_command_in_worker", wait_for_cancel)
    websocket = CancelCommandWebSocket()

    asyncio.run(command_loop(websocket, config()))

    assert websocket.sent == [
        {
            "type": "result",
            "command_id": "1",
            "routine": "vscode_type_random_text",
            "status": "cancelled",
            "message": COMMAND_CANCELLED_MESSAGE,
        }
    ]


def test_optional_float_allows_disabling_websocket_ping(monkeypatch):
    monkeypatch.setenv("CONTROL_AGENT_WS_PING_INTERVAL_SECONDS", "off")
    monkeypatch.setenv("CONTROL_AGENT_WS_PING_TIMEOUT_SECONDS", "0")

    assert env_optional_float("CONTROL_AGENT_WS_PING_INTERVAL_SECONDS", 20, 1) is None
    assert env_optional_float("CONTROL_AGENT_WS_PING_TIMEOUT_SECONDS", 20, 1) is None


def test_load_config_disables_websocket_ping_timeout_by_default(monkeypatch):
    monkeypatch.delenv("CONTROL_AGENT_WS_PING_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("CONTROL_AGENT_WS_PING_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CONTROL_AGENT_COMMAND_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CONTROL_COMMAND_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_DSN", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_TRACES_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_SEND_DEFAULT_PII", raising=False)

    loaded = load_config()

    assert loaded.websocket_ping_interval_seconds is None
    assert loaded.websocket_ping_timeout_seconds is None
    assert loaded.command_timeout_seconds == 120
    assert loaded.sentry_dsn == ""
    assert loaded.sentry_environment == "production"
    assert loaded.sentry_release == ""
    assert loaded.sentry_traces_sample_rate == 0.0
    assert loaded.sentry_send_default_pii is False


def test_load_env_file_sets_missing_environment_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CONTROL_AGENT_ID=file-agent",
                "CONTROL_AGENT_DRY_RUN=false",
                "IGNORED_WITHOUT_EQUALS",
                "QUOTED_VALUE=\"hello world\"",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CONTROL_AGENT_ID", raising=False)
    monkeypatch.setenv("CONTROL_AGENT_DRY_RUN", "true")
    monkeypatch.delenv("QUOTED_VALUE", raising=False)

    load_env_file(env_file)

    assert os.environ["CONTROL_AGENT_ID"] == "file-agent"
    assert os.environ["CONTROL_AGENT_DRY_RUN"] == "true"
    assert os.environ["QUOTED_VALUE"] == "hello world"


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
