from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import shutil
import string
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import webbrowser


SUPPORTED_COMMANDS = {"vscode_type_random_text", "open_discord", "open_gmail", "mouse_click"}
MOUSE_BUTTONS = {"left", "right", "middle"}
COMMAND_BUSY_MESSAGE = "Agente ocupado executando outro comando; tente novamente depois."
PYAUTOGUI_FAILSAFE_MESSAGE = (
    "PyAutoGUI bloqueou a automacao porque o cursor esta em um canto da tela. "
    "Mova o mouse para fora dos cantos e tente novamente."
)


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
    reconnect_seconds: float
    websocket_ping_interval_seconds: float | None
    websocket_ping_timeout_seconds: float | None
    command_timeout_seconds: float
    sentry_dsn: str
    sentry_environment: str
    sentry_release: str
    sentry_traces_sample_rate: float
    sentry_send_default_pii: bool


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def env_float_between(name: str, default: float, minimum: float, maximum: float) -> float:
    return min(maximum, env_float(name, default, minimum))


def env_optional_float(name: str, default: float | None, minimum: float) -> float | None:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"", "0", "false", "no", "off", "none", "disabled"}:
        return None
    try:
        parsed = float(normalized)
    except ValueError:
        return default
    return max(minimum, parsed)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def load_config() -> AgentConfig:
    load_env_file(Path(__file__).with_name(".env"))

    return AgentConfig(
        hub_ws_url=os.getenv("CONTROL_HUB_WS_URL", "ws://localhost:8080/ws/agent"),
        pairing_token=os.getenv("CONTROL_PAIRING_TOKEN", "dev-change-me"),
        agent_id=os.getenv("CONTROL_AGENT_ID", "windows-agent"),
        dry_run=env_bool("CONTROL_AGENT_DRY_RUN", True),
        heartbeat_seconds=env_float("CONTROL_AGENT_HEARTBEAT_SECONDS", 10, 1),
        vscode_executable=os.getenv("VSCODE_EXECUTABLE", "code"),
        vscode_target_file=os.getenv("VSCODE_TARGET_FILE", ""),
        discord_executable=os.getenv("DISCORD_EXECUTABLE", ""),
        chrome_executable=os.getenv("CHROME_EXECUTABLE", "chrome"),
        reconnect_seconds=env_float("CONTROL_AGENT_RECONNECT_SECONDS", 5, 1),
        websocket_ping_interval_seconds=env_optional_float("CONTROL_AGENT_WS_PING_INTERVAL_SECONDS", None, 1),
        websocket_ping_timeout_seconds=env_optional_float("CONTROL_AGENT_WS_PING_TIMEOUT_SECONDS", None, 1),
        command_timeout_seconds=env_float(
            "CONTROL_AGENT_COMMAND_TIMEOUT_SECONDS",
            env_float("CONTROL_COMMAND_TIMEOUT_SECONDS", 120, 1),
            1,
        ),
        sentry_dsn=os.getenv("CONTROL_SENTRY_DSN", os.getenv("SENTRY_DSN", "")).strip(),
        sentry_environment=os.getenv("CONTROL_SENTRY_ENVIRONMENT", os.getenv("SENTRY_ENVIRONMENT", "production")).strip(),
        sentry_release=os.getenv("CONTROL_SENTRY_RELEASE", os.getenv("SENTRY_RELEASE", "")).strip(),
        sentry_traces_sample_rate=env_float_between("CONTROL_SENTRY_TRACES_SAMPLE_RATE", 0.0, 0.0, 1.0),
        sentry_send_default_pii=env_bool("CONTROL_SENTRY_SEND_DEFAULT_PII", False),
    )


def setup_sentry(config: AgentConfig) -> bool:
    if not config.sentry_dsn:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=config.sentry_dsn,
        environment=config.sentry_environment or None,
        release=config.sentry_release or None,
        traces_sample_rate=config.sentry_traces_sample_rate,
        send_default_pii=config.sentry_send_default_pii,
    )
    sentry_sdk.set_tag("component", "windows_agent")
    sentry_sdk.set_tag("agent_id", config.agent_id)
    return True


def capture_exception(exc: BaseException) -> None:
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def build_agent_url(config: AgentConfig) -> str:
    parts = urlsplit(config.hub_ws_url)
    query = dict(parse_qsl(parts.query))
    query["token"] = config.pairing_token
    query["agent_id"] = config.agent_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def random_identifier(prefix: str = "value") -> str:
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
    return f"{prefix}{suffix}"


def random_go_code(length: int) -> str:
    name = random_identifier("item")
    limit = random.randint(2, 8)
    lines = [
        "package main",
        "",
        'import "fmt"',
        "",
        "func main() {",
        f"    {name} := 0",
        f"    for i := 0; i < {limit}; i++ {{",
        f"        {name} += i",
        "    }",
        f'    fmt.Println("total", {name})',
    ]
    while len("\n".join([*lines, "}"])) < length:
        label = random_identifier("trace")
        value = random.randint(1, 99)
        lines.append(f'    fmt.Println("{label}", {name}+{value})')
    lines.append("}")
    return "\n".join(lines) + "\n"


def expand_path(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def existing_path(value: str | None) -> str | None:
    if not value:
        return None
    expanded = expand_path(value)
    return expanded if Path(expanded).exists() else None


def resolve_executable(configured: str, common_paths: list[str]) -> str | None:
    if configured:
        configured_path = existing_path(configured)
        if configured_path:
            return configured_path
        located = shutil.which(configured)
        if located:
            return located

    for path in common_paths:
        found = existing_path(path)
        if found:
            return found
    return None


def vscode_executable(config: AgentConfig) -> str | None:
    return resolve_executable(
        config.vscode_executable,
        [
            r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",
            r"%ProgramFiles%\Microsoft VS Code\Code.exe",
            r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe",
        ],
    )


def chrome_executable(config: AgentConfig) -> str | None:
    return resolve_executable(
        config.chrome_executable,
        [
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        ],
    )


def result(command: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    return {
        "type": "result",
        "command_id": command.get("id", ""),
        "routine": command.get("type", "unknown"),
        "status": status,
        "message": message,
    }


def is_mouse_failsafe_point(pyautogui: Any, x: int, y: int) -> bool:
    width, height = pyautogui.size()
    return (x, y) in {
        (0, 0),
        (0, height - 1),
        (width - 1, 0),
        (width - 1, height - 1),
    }


def random_mouse_point(pyautogui: Any, margin: int, rng: random.Random | None = None) -> tuple[int, int]:
    rng = rng or random
    width, height = pyautogui.size()
    max_margin_x = max(1, (int(width) - 1) // 2)
    max_margin_y = max(1, (int(height) - 1) // 2)
    safe_margin = max(1, min(int(margin), max_margin_x, max_margin_y))
    min_x = safe_margin
    max_x = max(safe_margin, int(width) - safe_margin - 1)
    min_y = safe_margin
    max_y = max(safe_margin, int(height) - safe_margin - 1)
    return rng.randint(min_x, max_x), rng.randint(min_y, max_y)


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
        if command_type == "mouse_click":
            return await handle_mouse_click(command, config)
    except Exception as exc:  # pragma: no cover - final safety net for runtime automation errors
        capture_exception(exc)
        return result(command, "failure", f"Erro ao executar {command_type}: {exc}")

    return result(command, "failure", f"Comando sem handler: {command_type}")


async def handle_vscode(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    params = command.get("params") or {}
    target_file = str(params.get("target_file") or config.vscode_target_file).strip()
    if not target_file:
        return result(command, "failure", "Arquivo alvo do VS Code nao configurado.")
    target_file = expand_path(target_file)
    target_path = Path(target_file)
    if target_path.exists() and target_path.is_dir():
        return result(command, "failure", f"Arquivo alvo do VS Code aponta para uma pasta: {target_file}")
    if not target_path.parent.exists():
        return result(command, "failure", f"Pasta do arquivo alvo nao existe no Windows: {target_path.parent}")

    try:
        text_length = int(params.get("text_length", 80))
    except (TypeError, ValueError):
        text_length = 80
    text_length = max(1, min(text_length, 500))
    text = random_go_code(text_length)
    try:
        typing_interval = float(params.get("typing_interval_seconds", 0.08))
    except (TypeError, ValueError):
        typing_interval = 0.08
    typing_interval = max(0, min(typing_interval, 2))

    if config.dry_run:
        return result(command, "success", f"Dry-run VS Code: abriria {target_file} e digitaria codigo Go com {len(text)} caracteres.")

    executable = vscode_executable(config)
    if executable:
        try:
            subprocess.Popen([executable, target_file])
        except FileNotFoundError:
            return result(command, "failure", f"Executavel do VS Code nao encontrado: {executable}")
        except OSError as exc:
            return result(command, "failure", f"Falha ao abrir VS Code em {target_file}: {exc}")
    elif os.name == "nt":
        if not target_path.exists():
            return result(
                command,
                "failure",
                f"VS Code nao encontrado e arquivo alvo ainda nao existe para abertura por associacao: {target_file}",
            )
        try:
            os.startfile(target_file)  # type: ignore[attr-defined]
        except OSError as exc:
            return result(command, "failure", f"Falha ao abrir arquivo alvo no Windows: {target_file}. Detalhe: {exc}")
    else:
        return result(command, "failure", "VS Code nao encontrado no PATH nem nos caminhos padrao.")
    await asyncio.sleep(2.5)

    try:
        import pyautogui
    except ImportError:
        return result(command, "failure", "pyautogui nao instalado no agente Windows.")

    try:
        pyautogui.hotkey("ctrl", "end")
        pyautogui.press("enter")
        await type_text(pyautogui, text, typing_interval)
    except pyautogui.FailSafeException:
        return result(command, "failure", PYAUTOGUI_FAILSAFE_MESSAGE)
    return result(command, "success", f"Texto digitado em {target_file}.")


async def type_text(
    pyautogui: Any,
    text: str,
    typing_interval: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    for index, character in enumerate(text):
        if character == "\n":
            pyautogui.press("enter")
        else:
            pyautogui.write(character, interval=0)
        if typing_interval > 0 and index < len(text) - 1:
            await sleep(typing_interval)


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

    executable = chrome_executable(config)
    if executable:
        subprocess.Popen([executable, url])
    elif os.name == "nt":
        webbrowser.open(url)
    else:
        return result(command, "failure", "Chrome nao encontrado no PATH nem nos caminhos padrao.")
    await asyncio.sleep(1)
    return result(command, "success", "Chrome aberto no Gmail. Login, se necessario, e manual.")


async def handle_mouse_click(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    params = command.get("params") or {}
    try:
        clicks = int(params.get("clicks", 1))
        margin = int(params.get("margin", 100))
    except (TypeError, ValueError):
        return result(command, "failure", "Parametros do click do mouse devem ser numeros inteiros.")

    button = str(params.get("button", "left")).strip().lower()
    if button not in MOUSE_BUTTONS:
        return result(command, "failure", "Botao do mouse deve ser left, right ou middle.")
    if not 1 <= clicks <= 10:
        return result(command, "failure", "Quantidade de clicks do mouse deve ficar entre 1 e 10.")
    if not 1 <= margin <= 1000:
        return result(command, "failure", "Margem segura do click do mouse deve ficar entre 1 e 1000 pixels.")

    if config.dry_run:
        return result(command, "success", f"Dry-run Mouse: clicaria {button} em ponto aleatorio com margem {margin}px {clicks} vez(es).")

    try:
        import pyautogui
    except ImportError:
        return result(command, "failure", "pyautogui nao instalado no agente Windows.")

    x, y = random_mouse_point(pyautogui, margin)
    if is_mouse_failsafe_point(pyautogui, x, y):
        return result(
            command,
            "failure",
            "Ponto aleatorio coincidiu com um canto de fail-safe do PyAutoGUI. Tente novamente com margem maior.",
        )

    try:
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    except pyautogui.FailSafeException:
        return result(command, "failure", PYAUTOGUI_FAILSAFE_MESSAGE)
    await asyncio.sleep(0.2)
    return result(command, "success", f"Mouse clicado em ({x}, {y}) com botao {button} {clicks} vez(es).")


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


async def command_loop(websocket: Any, config: AgentConfig) -> None:
    command_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    command_busy = asyncio.Event()
    worker_task = asyncio.create_task(command_worker_loop(websocket, config, command_queue, command_busy))
    try:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message.get("type") != "command":
                continue
            command = message.get("command") or {}
            if command_busy.is_set() or not command_queue.empty():
                await websocket.send(json.dumps(result(command, "failure", COMMAND_BUSY_MESSAGE)))
                continue
            command_queue.put_nowait(command)
    finally:
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)


async def command_worker_loop(
    websocket: Any,
    config: AgentConfig,
    command_queue: asyncio.Queue[dict[str, Any]],
    command_busy: asyncio.Event,
) -> None:
    while True:
        command = await command_queue.get()
        command_busy.set()
        try:
            command_result = await dispatch_command_in_worker(command, config)
            await websocket.send(json.dumps(command_result))
        finally:
            command_busy.clear()
            command_queue.task_done()


async def dispatch_command_in_worker(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    return await asyncio.to_thread(lambda: asyncio.run(dispatch_command_with_timeout(command, config)))


async def dispatch_command_with_timeout(command: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(dispatch_command(command, config), timeout=config.command_timeout_seconds)
    except asyncio.TimeoutError:
        return result(command, "failure", f"Comando excedeu o tempo limite de {config.command_timeout_seconds:g}s.")


async def run_connection(websocket: Any, config: AgentConfig) -> None:
    heartbeat_task = asyncio.create_task(heartbeat_loop(websocket, config))
    command_task = asyncio.create_task(command_loop(websocket, config))
    tasks = {heartbeat_task, command_task}
    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    finally:
        remaining = [task for task in tasks if not task.done()]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)


async def run_agent(config: AgentConfig) -> None:
    import websockets

    url = build_agent_url(config)
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=config.websocket_ping_interval_seconds,
                ping_timeout=config.websocket_ping_timeout_seconds,
            ) as websocket:
                await run_connection(websocket, config)
        except Exception as exc:
            print(f"Agent connection failed: {exc}. Retrying in {config.reconnect_seconds:g}s.", flush=True)
        await asyncio.sleep(config.reconnect_seconds)


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
                    "heartbeat_seconds": config.heartbeat_seconds,
                    "reconnect_seconds": config.reconnect_seconds,
                    "websocket_ping_interval_seconds": config.websocket_ping_interval_seconds,
                    "websocket_ping_timeout_seconds": config.websocket_ping_timeout_seconds,
                    "command_timeout_seconds": config.command_timeout_seconds,
                    "sentry_enabled": bool(config.sentry_dsn),
                    "sentry_environment": config.sentry_environment,
                    "sentry_release": config.sentry_release,
                    "sentry_traces_sample_rate": config.sentry_traces_sample_rate,
                    "sentry_send_default_pii": config.sentry_send_default_pii,
                },
                indent=2,
            )
        )
        return

    setup_sentry(config)
    asyncio.run(run_agent(config))


if __name__ == "__main__":
    main()
