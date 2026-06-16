import asyncio

from windows_agent.agent import AgentConfig, dispatch_command, resolve_executable


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


def test_gmail_dry_run_succeeds_without_opening_browser():
    response = asyncio.run(dispatch_command({"id": "1", "type": "open_gmail", "params": {}}, config()))

    assert response["status"] == "success"
    assert "Dry-run" in response["message"]


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
