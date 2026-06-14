from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
import random
import string
import subprocess
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import webbrowser


SUPPORTED_COMMANDS = {"vscode_type_random_text", "open_discord", "open_gmail"}


@dataclass(frozen=True)
class AgentConfig:
    hub_ws_url: str
    pairing_token: str
    agent_id: str
    dry_run: bool
    heartbeat_seconds: float
    vscode_executable: str
    vscode_target_file: str
    discord_executable: str
    chrome_executable: str


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> AgentConfig:
    return AgentConfig(
        hub_ws_url=os.getenv("CONTROL_HUB_WS_URL", "ws://localhost:8080/ws/agent"),
        pairing_token=os.getenv("CONTROL_PAIRING_TOKEN", "dev-change-me"),
        agent_id=os.getenv("CONTROL_AGENT_ID", "windows-agent"),
        dry_run=env_bool("CONTROL_AGENT_DRY_RUN", True),
        heartbeat_seconds=float(os.getenv("CONTROL_AGENT_HEARTBEAT_SECONDS", "10")),
        vscode_executable=os.getenv("VSCODE_EXECUTABLE", "code"),
        vscode_target_file=os.getenv("VSCODE_TARGET_FILE", ""),
        discord_executable=os.getenv("DISCORD_EXECUTABLE", ""),
        chrome_executable=os.getenv("CHROME_EXECUTABLE", "chrome"),
    )


def build_agent_url(config: AgentConfig) -> str:
    parts = urlsplit(config.hub_ws_url)
    query = dict(parse_qsl(parts.query))
    query["token"] = config.pairing_token
    query["agent_id"] = config.agent_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def random_text(length: int) -> str:
    alphabet = string.ascii_letters + string.digits + "     .,;:-_"
    text = "".join(random.choice(alphabet) for _ in range(length)).strip()
    return text or "control"


def result(command: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    return {
        "type": "result",
        "command_id": command.get("id", ""),
        "routine": command.get("type", "unknown"),
        "status": status,
        "message": message,
    }


async def dispatch_command(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    command_type = str(command.get("type", ""))
    if command_type not in SUPPORTED_COMMANDS:
        return result(command, "failure", f"Comando nao suportado: {command_type}")

    try:
        if command_type == "vscode_type_random_text":
            return await handle_vscode(command, config)
        if command_type == "open_discord":
            return await handle_discord(command, config)
        if command_type == "open_gmail":
            return await handle_gmail(command, config)
    except Exception as exc:  # pragma: no cover - final safety net for runtime automation errors
        return result(command, "failure", f"Erro ao executar {command_type}: {exc}")

    return result(command, "failure", f"Comando sem handler: {command_type}")


async def handle_vscode(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    params = command.get("params") or {}
    target_file = str(params.get("target_file") or config.vscode_target_file).strip()
    if not target_file:
        return result(command, "failure", "Arquivo alvo do VS Code nao configurado.")

    try:
        text_length = int(params.get("text_length", 80))
    except (TypeError, ValueError):
        text_length = 80
    text_length = max(1, min(text_length, 500))
    text = random_text(text_length)

    if config.dry_run:
        return result(command, "success", f"Dry-run VS Code: abriria {target_file} e digitaria {len(text)} caracteres.")

    subprocess.Popen([config.vscode_executable, target_file])
    await asyncio.sleep(2.5)

    try:
        import pyautogui
    except ImportError:
        return result(command, "failure", "pyautogui nao instalado no agente Windows.")

    pyautogui.hotkey("ctrl", "end")
    pyautogui.press("enter")
    pyautogui.write(text, interval=0.03)
    return result(command, "success", f"Texto digitado em {target_file}.")


async def handle_discord(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    if config.dry_run:
        return result(command, "success", "Dry-run Discord: abriria ou focaria o Discord.")

    if config.discord_executable:
        subprocess.Popen([config.discord_executable])
    elif os.name == "nt":
        os.startfile("discord://")  # type: ignore[attr-defined]
    else:
        return result(command, "failure", "Abertura por protocolo Discord exige Windows.")
    await asyncio.sleep(1)
    return result(command, "success", "Discord aberto ou focado.")


async def handle_gmail(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    params = command.get("params") or {}
    url = str(params.get("url") or "https://mail.google.com/")

    if config.dry_run:
        return result(command, "success", f"Dry-run Gmail: abriria {url}.")

    if config.chrome_executable:
        subprocess.Popen([config.chrome_executable, url])
    else:
        webbrowser.open(url)
    await asyncio.sleep(1)
    return result(command, "success", "Chrome aberto no Gmail. Login, se necessario, e manual.")


async def heartbeat_loop(websocket: Any, config: AgentConfig) -> None:
    while True:
        await websocket.send(
            json.dumps(
                {
                    "type": "heartbeat",
                    "agent_id": config.agent_id,
                    "message": "dry-run" if config.dry_run else "active",
                }
            )
        )
        await asyncio.sleep(config.heartbeat_seconds)


async def run_agent(config: AgentConfig) -> None:
    import websockets

    url = build_agent_url(config)
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as websocket:
                heartbeat_task = asyncio.create_task(heartbeat_loop(websocket, config))
                try:
                    async for raw_message in websocket:
                        message = json.loads(raw_message)
                        if message.get("type") != "command":
                            continue
                        command = message.get("command") or {}
                        command_result = await dispatch_command(command, config)
                        await websocket.send(json.dumps(command_result))
                finally:
                    heartbeat_task.cancel()
        except Exception as exc:
            print(f"Agent connection failed: {exc}. Retrying in 5s.", flush=True)
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Windows Activity Control agent")
    parser.add_argument("--print-config", action="store_true", help="Print safe config summary and exit")
    args = parser.parse_args()

    config = load_config()
    if args.print_config:
        print(
            json.dumps(
                {
                    "hub_ws_url": config.hub_ws_url,
                    "agent_id": config.agent_id,
                    "dry_run": config.dry_run,
                    "vscode_target_file": config.vscode_target_file,
                    "has_pairing_token": bool(config.pairing_token),
                },
                indent=2,
            )
        )
        return

    asyncio.run(run_agent(config))


if __name__ == "__main__":
    main()

