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
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import webbrowser
import re

from .mouse_humanizer import bezier_path, choose_interest_point, overshoot_point, safe_bounds


SUPPORTED_COMMANDS = {"vscode_type_random_text", "open_discord", "open_gmail", "mouse_click", "mouse_move", "scenario"}
MOUSE_BUTTONS = {"left", "right", "middle"}
CODE_LANGUAGES = ("go", "python", "js", "typescript", "rust", "java")
CONTROL_CANCEL_ACTIVE_COMMAND = "cancel_active_command"
COMMAND_BUSY_MESSAGE = "Agente ocupado executando outro comando; tente novamente depois."
COMMAND_CANCELLED_MESSAGE = "Comando cancelado pelo hub."
PYAUTOGUI_FAILSAFE_MESSAGE = (
    "PyAutoGUI bloqueou a automacao porque o cursor esta em um canto da tela. "
    "Mova o mouse para fora dos cantos e tente novamente."
)
AGENT_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
AGENT_PROTOCOL_VERSION = "2"


class CommandCancelled(Exception):
    pass


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
    agent_name: str = ""
    reconnect_max_seconds: float = 60.0
    heartbeat_jitter_seconds: float = 0.5


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

    agent_id = os.getenv("CONTROL_AGENT_ID", "").strip().lower()
    if not agent_id:
        raise ValueError("CONTROL_AGENT_ID e obrigatorio para identificar este PC de forma unica.")
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise ValueError(
            "CONTROL_AGENT_ID deve ter 1-64 caracteres minusculos e usar letras, numeros, '.', '_' ou '-'."
        )

    return AgentConfig(
        hub_ws_url=os.getenv("CONTROL_HUB_WS_URL", "ws://localhost:8080/ws/agent"),
        pairing_token=os.getenv("CONTROL_PAIRING_TOKEN", "dev-change-me"),
        agent_id=agent_id,
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
        agent_name=os.getenv("CONTROL_AGENT_NAME", os.getenv("COMPUTERNAME", agent_id)).strip() or agent_id,
        reconnect_max_seconds=env_float("CONTROL_AGENT_RECONNECT_MAX_SECONDS", 60, 1),
        heartbeat_jitter_seconds=env_float_between("CONTROL_AGENT_HEARTBEAT_JITTER_SECONDS", 0.5, 0.0, 5.0),
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
    query["agent_id"] = config.agent_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def connection_headers(config: AgentConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.pairing_token}"}


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


def _extend_lines(lines: list[str], length: int, line_factory: Callable[[], str]) -> str:
    while len("\n".join(lines)) < length:
        lines.append(line_factory())
    return "\n".join(lines) + "\n"


def random_python_code(length: int) -> str:
    name = random_identifier("total")
    limit = random.randint(3, 9)
    lines = [
        "from collections import defaultdict",
        "",
        "",
        "def summarize(values):",
        f"    {name} = 0",
        "    buckets = defaultdict(int)",
        f"    for index, value in enumerate(values[:{limit}]):",
        f"        {name} += value",
        "        buckets[index % 3] += value",
        f"    return {name}, dict(buckets)",
    ]
    return _extend_lines(lines, length, lambda: f"print(summarize([{random.randint(1, 9)}, {random.randint(1, 9)}, {random.randint(1, 9)}]))")


def random_js_code(length: int) -> str:
    name = random_identifier("items")
    limit = random.randint(2, 7)
    lines = [
        f"const {name} = [1, 2, 3, 5, 8].slice(0, {limit});",
        "",
        f"const total = {name}.reduce((sum, value) => {{",
        "  return sum + value;",
        "}, 0);",
        "",
        "console.log({ total });",
    ]
    return _extend_lines(lines, length, lambda: f"console.debug('trace', total + {random.randint(1, 99)});")


def random_typescript_code(length: int) -> str:
    name = random_identifier("event")
    lines = [
        "type ActivityEvent = {",
        "  id: string;",
        "  score: number;",
        "};",
        "",
        f"const {name}: ActivityEvent = {{ id: 'evt-{random.randint(10, 99)}', score: {random.randint(1, 10)} }};",
        "",
        f"export const normalized = Math.min(1, {name}.score / 10);",
    ]
    return _extend_lines(lines, length, lambda: f"console.log('{random_identifier('checkpoint')}', normalized);")


def random_rust_code(length: int) -> str:
    name = random_identifier("total")
    limit = random.randint(3, 8)
    lines = [
        "fn main() {",
        f"    let mut {name} = 0;",
        f"    for index in 0..{limit} {{",
        f"        {name} += index;",
        "    }",
        f'    println!("total {{}}", {name});',
    ]
    while len("\n".join([*lines, "}"])) < length:
        lines.append(f'    println!("trace {{}}", {name} + {random.randint(1, 99)});')
    lines.append("}")
    return "\n".join(lines) + "\n"


def random_java_code(length: int) -> str:
    class_name = "Scratch" + "".join(random.choice(string.ascii_uppercase) for _ in range(3))
    name = random_identifier("total")
    limit = random.randint(3, 8)
    lines = [
        f"public class {class_name} {{",
        "    public static void main(String[] args) {",
        f"        int {name} = 0;",
        f"        for (int i = 0; i < {limit}; i++) {{",
        f"            {name} += i;",
        "        }",
        f'        System.out.println("total " + {name});',
    ]
    while len("\n".join([*lines, "    }", "}"])) < length:
        lines.append(f'        System.out.println("trace " + ({name} + {random.randint(1, 99)}));')
    lines.extend(["    }", "}"])
    return "\n".join(lines) + "\n"


def random_code(language: str, length: int) -> tuple[str, str]:
    normalized = str(language or "random").strip().lower()
    if normalized == "random":
        normalized = random.choice(CODE_LANGUAGES)
    generators: dict[str, Callable[[int], str]] = {
        "go": random_go_code,
        "python": random_python_code,
        "js": random_js_code,
        "typescript": random_typescript_code,
        "rust": random_rust_code,
        "java": random_java_code,
    }
    generator = generators.get(normalized, random_go_code)
    return generator(length), normalized if normalized in generators else "go"


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
    payload = {
        "type": "result",
        "command_id": command.get("id", ""),
        "routine": command.get("type", "unknown"),
        "status": status,
        "message": message,
    }
    for key in ("agent_id", "session_id"):
        if isinstance(command.get(key), str) and command[key]:
            payload[key] = command[key]
    return payload


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
    return choose_interest_point(pyautogui, margin, rng)


def clamp_mouse_destination(pyautogui: Any, x: int, y: int, margin: int) -> tuple[int, int]:
    width, height = pyautogui.size()
    min_x, min_y, max_x, max_y = safe_bounds(int(width), int(height), int(margin))
    return max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y))


async def move_mouse_humanized(
    pyautogui: Any,
    destination: tuple[int, int] | None = None,
    margin: int = 100,
    duration_seconds: float = 1.2,
    overshoot_chance: float = 0.15,
    cancel_event: threading.Event | None = None,
    rng: random.Random | None = None,
) -> tuple[int, int]:
    rng = rng or random
    width, height = pyautogui.size()
    if destination is None:
        destination = random_mouse_point(pyautogui, margin, rng)
    else:
        destination = clamp_mouse_destination(pyautogui, destination[0], destination[1], margin)

    if not hasattr(pyautogui, "moveTo"):
        return destination

    if hasattr(pyautogui, "position"):
        current_position = pyautogui.position()
        start = (int(current_position[0]), int(current_position[1]))
    else:
        start = (int(width) // 2, int(height) // 2)

    targets = [destination]
    if rng.random() < overshoot_chance:
        targets = [overshoot_point(start, destination, int(width), int(height), margin, rng), destination]

    remaining_start = start
    total_steps = max(50, min(100, int(duration_seconds * 60)))
    for target_index, target in enumerate(targets):
        segment_steps = max(12, total_steps // len(targets))
        path = bezier_path(remaining_start, target, segment_steps, rng)
        step_delay = max(0.002, duration_seconds / (segment_steps * len(targets)))
        for point in path[1:]:
            raise_if_cancelled(cancel_event)
            pyautogui.moveTo(point.x, point.y, duration=0)
            await cancellable_sleep(step_delay, cancel_event)
        remaining_start = target
        if target_index == 0 and len(targets) > 1:
            await cancellable_sleep(rng.uniform(0.05, 0.18), cancel_event)

    drift_x = rng.randint(-3, 3)
    drift_y = rng.randint(-3, 3)
    if drift_x or drift_y:
        final_x, final_y = clamp_mouse_destination(pyautogui, destination[0] + drift_x, destination[1] + drift_y, margin)
        pyautogui.moveTo(final_x, final_y, duration=0)
        await cancellable_sleep(rng.uniform(0.04, 0.12), cancel_event)
        pyautogui.moveTo(destination[0], destination[1], duration=0)
    return destination


def raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CommandCancelled


async def cancellable_sleep(
    delay: float,
    cancel_event: threading.Event | None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    if cancel_event is None:
        await sleep(delay)
        return

    deadline = time.monotonic() + delay
    while True:
        raise_if_cancelled(cancel_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await sleep(min(0.05, remaining))


async def dispatch_command(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    command_type = str(command.get("type", ""))
    if command_type not in SUPPORTED_COMMANDS:
        return result(command, "failure", f"Comando nao suportado: {command_type}")

    try:
        raise_if_cancelled(cancel_event)
        if command_type == "vscode_type_random_text":
            return await handle_vscode(command, config, cancel_event)
        if command_type == "open_discord":
            return await handle_discord(command, config, cancel_event)
        if command_type == "open_gmail":
            return await handle_gmail(command, config, cancel_event)
        if command_type == "mouse_click":
            return await handle_mouse_click(command, config, cancel_event)
        if command_type == "mouse_move":
            return await handle_mouse_move(command, config, cancel_event)
        if command_type == "scenario":
            return await handle_scenario(command, config, cancel_event)
    except CommandCancelled:
        return result(command, "cancelled", COMMAND_CANCELLED_MESSAGE)
    except Exception as exc:  # pragma: no cover - final safety net for runtime automation errors
        capture_exception(exc)
        return result(command, "failure", f"Erro ao executar {command_type}: {exc}")

    return result(command, "failure", f"Comando sem handler: {command_type}")


async def handle_vscode(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
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
    code_language = str(params.get("code_language", "random")).strip().lower()
    text, selected_language = random_code(code_language, text_length)
    try:
        typing_interval = float(params.get("typing_interval_seconds", 0.08))
    except (TypeError, ValueError):
        typing_interval = 0.08
    typing_interval = max(0, min(typing_interval, 2))
    try:
        typo_rate = float(params.get("typo_rate", 0.03))
    except (TypeError, ValueError):
        typo_rate = 0.03
    typo_rate = max(0, min(typo_rate, 0.1))
    try:
        thinking_pause_chance = float(params.get("thinking_pause_chance", 0.05))
    except (TypeError, ValueError):
        thinking_pause_chance = 0.05
    thinking_pause_chance = max(0, min(thinking_pause_chance, 0.2))

    raise_if_cancelled(cancel_event)
    if config.dry_run:
        return result(
            command,
            "success",
            f"Dry-run VS Code: abriria {target_file} e digitaria codigo {selected_language} com {len(text)} caracteres.",
        )

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
    await cancellable_sleep(2.5, cancel_event)

    try:
        import pyautogui
    except ImportError:
        return result(command, "failure", "pyautogui nao instalado no agente Windows.")

    try:
        raise_if_cancelled(cancel_event)
        pyautogui.hotkey("ctrl", "end")
        pyautogui.press("enter")
        await type_text(
            pyautogui,
            text,
            typing_interval,
            cancel_event=cancel_event,
            typo_rate=typo_rate,
            thinking_pause_chance=thinking_pause_chance,
            humanize=True,
        )
    except pyautogui.FailSafeException:
        return result(command, "failure", PYAUTOGUI_FAILSAFE_MESSAGE)
    return result(command, "success", f"Codigo {selected_language} digitado em {target_file}.")


async def type_text(
    pyautogui: Any,
    text: str,
    typing_interval: float,
    cancel_event: threading.Event | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    typo_rate: float = 0.0,
    thinking_pause_chance: float = 0.0,
    humanize: bool = False,
    rng: random.Random | None = None,
) -> None:
    rng = rng or random
    for index, character in enumerate(text):
        raise_if_cancelled(cancel_event)
        if humanize and _is_line_start(text, index) and _line_at(text, index).lstrip().startswith(("import ", "from ", "use ")):
            await cancellable_sleep(rng.uniform(0.5, 2.0), cancel_event, sleep=sleep)

        if character == "\n":
            pyautogui.press("enter")
        else:
            if humanize and typo_rate > 0 and rng.random() < typo_rate:
                await type_corrected_typo(pyautogui, character, cancel_event, sleep, rng)
            pyautogui.write(character, interval=0)
        if typing_interval > 0 and index < len(text) - 1:
            delay = humanized_key_delay(typing_interval, character, rng) if humanize else typing_interval
            await cancellable_sleep(delay, cancel_event, sleep=sleep)
        if humanize and character == "\n" and index < len(text) - 1:
            await maybe_thinking_pause(text, index, thinking_pause_chance, cancel_event, sleep, rng)


def _is_line_start(text: str, index: int) -> bool:
    return index == 0 or text[index - 1] == "\n"


def _line_at(text: str, index: int) -> str:
    end = text.find("\n", index)
    if end == -1:
        end = len(text)
    return text[index:end]


def _line_before(text: str, newline_index: int) -> str:
    start = text.rfind("\n", 0, newline_index)
    if start == -1:
        start = 0
    else:
        start += 1
    return text[start:newline_index]


def humanized_key_delay(base_interval: float, character: str, rng: random.Random | None = None) -> float:
    rng = rng or random
    if base_interval <= 0:
        return 0.0
    if character == "\n":
        return max(0.3, min(1.2, rng.gauss(0.75, 0.25)))
    multiplier = 0.7 if character.isalpha() or character == " " else 1.0
    if character in "{}()[];:,.<>+-=*/\\\"'`":
        multiplier = 1.5
    mean = base_interval * multiplier
    std_dev = max(0.005, base_interval * 0.4)
    return max(0.01, min(max(0.05, base_interval * 4), rng.gauss(mean, std_dev)))


async def type_corrected_typo(
    pyautogui: Any,
    correct_character: str,
    cancel_event: threading.Event | None,
    sleep: Callable[[float], Awaitable[None]],
    rng: random.Random,
) -> None:
    wrong_count = rng.randint(1, 3)
    candidates = string.ascii_lowercase + string.digits
    wrong_text = "".join(rng.choice(candidates) for _ in range(wrong_count))
    if correct_character and correct_character in wrong_text and len(candidates) > 1:
        wrong_text = wrong_text.replace(correct_character, rng.choice(candidates.replace(correct_character, "")), 1)
    for wrong_character in wrong_text:
        raise_if_cancelled(cancel_event)
        pyautogui.write(wrong_character, interval=0)
    await cancellable_sleep(rng.uniform(0.3, 0.8), cancel_event, sleep=sleep)
    for _ in wrong_text:
        raise_if_cancelled(cancel_event)
        pyautogui.press("backspace")


async def maybe_thinking_pause(
    text: str,
    newline_index: int,
    thinking_pause_chance: float,
    cancel_event: threading.Event | None,
    sleep: Callable[[float], Awaitable[None]],
    rng: random.Random,
) -> None:
    previous_line = _line_before(text, newline_index).strip()
    if not previous_line or previous_line.endswith(("}", "};", "):", ":", "{")):
        await cancellable_sleep(rng.uniform(1.0, 4.0), cancel_event, sleep=sleep)
        return
    if thinking_pause_chance > 0 and rng.random() < thinking_pause_chance:
        await cancellable_sleep(rng.uniform(2.0, 6.0), cancel_event, sleep=sleep)


async def handle_discord(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    raise_if_cancelled(cancel_event)
    if config.dry_run:
        return result(command, "success", "Dry-run Discord: abriria ou focaria o Discord.")

    if config.discord_executable:
        subprocess.Popen([config.discord_executable])
    elif os.name == "nt":
        os.startfile("discord://")  # type: ignore[attr-defined]
    else:
        return result(command, "failure", "Abertura por protocolo Discord exige Windows.")
    await cancellable_sleep(1, cancel_event)
    return result(command, "success", "Discord aberto ou focado.")


async def handle_gmail(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    params = command.get("params") or {}
    url = str(params.get("url") or "https://mail.google.com/")

    raise_if_cancelled(cancel_event)
    if config.dry_run:
        return result(command, "success", f"Dry-run Gmail: abriria {url}.")

    executable = chrome_executable(config)
    if executable:
        subprocess.Popen([executable, url])
    elif os.name == "nt":
        webbrowser.open(url)
    else:
        return result(command, "failure", "Chrome nao encontrado no PATH nem nos caminhos padrao.")
    await cancellable_sleep(1, cancel_event)
    return result(command, "success", "Chrome aberto no Gmail. Login, se necessario, e manual.")


async def handle_mouse_click(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    params = command.get("params") or {}
    try:
        clicks = int(params.get("clicks", 1))
        margin = int(params.get("margin", 100))
        duration_seconds = float(params.get("move_duration_seconds", params.get("duration_seconds", 1.2)))
        overshoot_chance = float(params.get("overshoot_chance", 0.15))
    except (TypeError, ValueError):
        return result(command, "failure", "Parametros do click do mouse devem ser numeros validos.")

    button = str(params.get("button", "left")).strip().lower()
    if button not in MOUSE_BUTTONS:
        return result(command, "failure", "Botao do mouse deve ser left, right ou middle.")
    if not 1 <= clicks <= 10:
        return result(command, "failure", "Quantidade de clicks do mouse deve ficar entre 1 e 10.")
    if not 1 <= margin <= 1000:
        return result(command, "failure", "Margem segura do click do mouse deve ficar entre 1 e 1000 pixels.")
    if not 0.5 <= duration_seconds <= 3.0:
        return result(command, "failure", "Duracao do movimento do mouse deve ficar entre 0.5 e 3 segundos.")
    if not 0 <= overshoot_chance <= 0.3:
        return result(command, "failure", "Chance de overshoot do mouse deve ficar entre 0 e 0.3.")

    raise_if_cancelled(cancel_event)
    if config.dry_run:
        return result(
            command,
            "success",
            f"Dry-run Mouse: moveria com curva e clicaria {button} em ponto aleatorio de interesse com margem {margin}px {clicks} vez(es).",
        )

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
        await move_mouse_humanized(
            pyautogui,
            (x, y),
            margin=margin,
            duration_seconds=duration_seconds,
            overshoot_chance=overshoot_chance,
            cancel_event=cancel_event,
        )
        await cancellable_sleep(random.uniform(0.1, 0.5), cancel_event)
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    except pyautogui.FailSafeException:
        return result(command, "failure", PYAUTOGUI_FAILSAFE_MESSAGE)
    await cancellable_sleep(0.2, cancel_event)
    return result(command, "success", f"Mouse clicado em ({x}, {y}) com botao {button} {clicks} vez(es).")


async def handle_mouse_move(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    params = command.get("params") or {}
    try:
        margin = int(params.get("margin", 100))
        duration_seconds = float(params.get("duration_seconds", 1.2))
        overshoot_chance = float(params.get("overshoot_chance", 0.15))
    except (TypeError, ValueError):
        return result(command, "failure", "Parametros do movimento do mouse devem ser numeros validos.")

    if not 1 <= margin <= 1000:
        return result(command, "failure", "Margem segura do mouse deve ficar entre 1 e 1000 pixels.")
    if not 0.5 <= duration_seconds <= 3.0:
        return result(command, "failure", "Duracao do movimento do mouse deve ficar entre 0.5 e 3 segundos.")
    if not 0 <= overshoot_chance <= 0.3:
        return result(command, "failure", "Chance de overshoot do mouse deve ficar entre 0 e 0.3.")

    raise_if_cancelled(cancel_event)
    if config.dry_run:
        return result(command, "success", f"Dry-run Mouse: moveria para zona de interesse em {duration_seconds:g}s.")

    try:
        import pyautogui
    except ImportError:
        return result(command, "failure", "pyautogui nao instalado no agente Windows.")

    try:
        x, y = await move_mouse_humanized(
            pyautogui,
            margin=margin,
            duration_seconds=duration_seconds,
            overshoot_chance=overshoot_chance,
            cancel_event=cancel_event,
        )
    except pyautogui.FailSafeException:
        return result(command, "failure", PYAUTOGUI_FAILSAFE_MESSAGE)
    return result(command, "success", f"Mouse movido para ({x}, {y}) em zona de interesse.")


async def handle_scenario(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    params = command.get("params") or {}
    scenario_type = str(params.get("scenario_type", "unknown"))
    actions = params.get("actions") or []
    if not isinstance(actions, list) or not actions:
        return result(command, "failure", "Cenario sem acoes validas.")

    raise_if_cancelled(cancel_event)
    if config.dry_run:
        return result(command, "success", f"Dry-run Cenario {scenario_type}: executaria {len(actions)} sub-acoes.")

    try:
        import pyautogui
    except ImportError:
        return result(command, "failure", "pyautogui nao instalado no agente Windows.")

    try:
        for action in actions:
            error = await execute_scenario_action(pyautogui, action, config, cancel_event)
            if error:
                return result(command, "failure", error)
    except pyautogui.FailSafeException:
        return result(command, "failure", PYAUTOGUI_FAILSAFE_MESSAGE)
    return result(command, "success", f"Cenario {scenario_type} executado com {len(actions)} sub-acoes.")


async def execute_scenario_action(
    pyautogui: Any,
    action: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None,
) -> str | None:
    if not isinstance(action, dict):
        return "Sub-acao de cenario invalida."
    action_type = str(action.get("type", "")).strip().lower()
    raise_if_cancelled(cancel_event)

    if action_type == "wait":
        minimum = float(action.get("min_seconds", action.get("seconds", 1)))
        maximum = float(action.get("max_seconds", minimum))
        await cancellable_sleep(random.uniform(max(0, minimum), max(minimum, maximum)), cancel_event)
        return None

    if action_type == "open_app":
        return await open_app_for_scenario(action, config, cancel_event)

    if action_type == "mouse_move":
        margin = int(action.get("margin", 100))
        duration = float(action.get("duration_seconds", 1.2))
        overshoot = float(action.get("overshoot_chance", 0.15))
        await move_mouse_humanized(pyautogui, margin=margin, duration_seconds=duration, overshoot_chance=overshoot, cancel_event=cancel_event)
        return None

    if action_type == "mouse_click":
        button = str(action.get("button", "left")).strip().lower()
        if button not in MOUSE_BUTTONS:
            return "Botao do mouse deve ser left, right ou middle."
        margin = int(action.get("margin", 100))
        duration = float(action.get("move_duration_seconds", 1.2))
        overshoot = float(action.get("overshoot_chance", 0.15))
        clicks = int(action.get("clicks", 1))
        x, y = await move_mouse_humanized(pyautogui, margin=margin, duration_seconds=duration, overshoot_chance=overshoot, cancel_event=cancel_event)
        await cancellable_sleep(random.uniform(0.1, 0.5), cancel_event)
        pyautogui.click(x=x, y=y, button=button, clicks=max(1, min(10, clicks)))
        return None

    if action_type == "scroll":
        await humanized_scroll(
            pyautogui,
            direction=str(action.get("direction", "down")),
            bursts=max(1, min(5, int(action.get("bursts", 2)))),
            cancel_event=cancel_event,
        )
        return None

    if action_type == "hotkey":
        keys = action.get("keys") or []
        if not isinstance(keys, list) or not keys:
            return "Hotkey do cenario precisa informar teclas."
        pyautogui.hotkey(*[str(key) for key in keys])
        await cancellable_sleep(random.uniform(0.18, 0.75), cancel_event)
        return None

    if action_type == "alt_tab":
        await realistic_alt_tab(pyautogui, cancel_event)
        return None

    if action_type == "type_text":
        await type_scenario_text(pyautogui, action, cancel_event)
        return None

    return f"Sub-acao de cenario nao suportada: {action_type}"


async def open_app_for_scenario(
    action: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None,
) -> str | None:
    app = str(action.get("app", "")).strip().lower()
    if app == "vscode":
        target_file = expand_path(str(action.get("target_file") or config.vscode_target_file).strip())
        if not target_file:
            return "Arquivo alvo do VS Code nao configurado."
        target_path = Path(target_file)
        if target_path.exists() and target_path.is_dir():
            return f"Arquivo alvo do VS Code aponta para uma pasta: {target_file}"
        if not target_path.parent.exists():
            return f"Pasta do arquivo alvo nao existe no Windows: {target_path.parent}"
        executable = vscode_executable(config)
        if executable:
            subprocess.Popen([executable, target_file])
        elif os.name == "nt" and target_path.exists():
            os.startfile(target_file)  # type: ignore[attr-defined]
        else:
            return "VS Code nao encontrado no PATH nem nos caminhos padrao."
        await cancellable_sleep(2.0, cancel_event)
        return None

    if app == "discord":
        if config.discord_executable:
            subprocess.Popen([config.discord_executable])
        elif os.name == "nt":
            os.startfile("discord://")  # type: ignore[attr-defined]
        else:
            return "Abertura por protocolo Discord exige Windows."
        await cancellable_sleep(1.0, cancel_event)
        return None

    if app == "gmail":
        url = str(action.get("url") or "https://mail.google.com/")
        executable = chrome_executable(config)
        if executable:
            subprocess.Popen([executable, url])
        elif os.name == "nt":
            webbrowser.open(url)
        else:
            return "Chrome nao encontrado no PATH nem nos caminhos padrao."
        await cancellable_sleep(1.0, cancel_event)
        return None

    return f"App do cenario nao suportado: {app}"


async def type_scenario_text(
    pyautogui: Any,
    action: dict[str, Any],
    cancel_event: threading.Event | None,
) -> None:
    if str(action.get("text_kind", "")).lower() == "code":
        try:
            text_length = int(action.get("text_length", 80))
        except (TypeError, ValueError):
            text_length = 80
        text, _language = random_code(str(action.get("code_language", "random")), max(1, min(500, text_length)))
    else:
        text = str(action.get("text", ""))
    try:
        interval = float(action.get("typing_interval_seconds", 0.08))
    except (TypeError, ValueError):
        interval = 0.08
    try:
        typo_rate = float(action.get("typo_rate", 0.03))
    except (TypeError, ValueError):
        typo_rate = 0.03
    try:
        thinking_pause_chance = float(action.get("thinking_pause_chance", 0.05))
    except (TypeError, ValueError):
        thinking_pause_chance = 0.05
    await type_text(
        pyautogui,
        text,
        max(0.0, min(2.0, interval)),
        cancel_event=cancel_event,
        typo_rate=max(0.0, min(0.1, typo_rate)),
        thinking_pause_chance=max(0.0, min(0.2, thinking_pause_chance)),
        humanize=True,
    )


async def humanized_scroll(
    pyautogui: Any,
    direction: str = "down",
    bursts: int = 2,
    cancel_event: threading.Event | None = None,
    rng: random.Random | None = None,
) -> None:
    rng = rng or random
    normalized = direction.strip().lower()
    if normalized not in {"up", "down", "random"}:
        normalized = "down"
    for _ in range(max(1, bursts)):
        actual_direction = normalized
        if actual_direction == "random":
            actual_direction = "down" if rng.random() < 0.8 else "up"
        sign = -1 if actual_direction == "down" else 1
        for _flick in range(rng.randint(2, 5)):
            raise_if_cancelled(cancel_event)
            pyautogui.scroll(sign * rng.randint(2, 6))
            await cancellable_sleep(rng.uniform(0.04, 0.18), cancel_event)
        if rng.random() < 0.18:
            pyautogui.scroll(-sign * rng.randint(1, 3))
        await cancellable_sleep(rng.uniform(0.5, 2.0), cancel_event)


async def realistic_alt_tab(
    pyautogui: Any,
    cancel_event: threading.Event | None = None,
    rng: random.Random | None = None,
) -> None:
    rng = rng or random
    tabs = rng.randint(1, 3)
    pyautogui.keyDown("alt")
    try:
        for _ in range(tabs):
            raise_if_cancelled(cancel_event)
            pyautogui.press("tab")
            await cancellable_sleep(rng.uniform(0.12, 0.35), cancel_event)
        await cancellable_sleep(rng.uniform(0.5, 1.5), cancel_event)
    finally:
        pyautogui.keyUp("alt")


def hello_message(config: AgentConfig) -> dict[str, Any]:
    return {
        "type": "hello",
        "agent_id": config.agent_id,
        "name": config.agent_name or config.agent_id,
        "version": "windows-agent-2",
        "protocol": AGENT_PROTOCOL_VERSION,
        "dry_run": config.dry_run,
        "execution_idle": True,
        "capabilities": sorted(SUPPORTED_COMMANDS),
    }


async def heartbeat_loop(websocket: Any, config: AgentConfig, connection: dict[str, Any] | None = None) -> None:
    while True:
        payload = {
            "type": "heartbeat",
            "agent_id": config.agent_id,
            "message": "dry-run" if config.dry_run else "active",
        }
        session_id = (connection or {}).get("session_id")
        if isinstance(session_id, str) and session_id:
            payload["session_id"] = session_id
        await websocket.send(
            json.dumps(payload)
        )
        jitter = min(config.heartbeat_jitter_seconds, max(0.0, config.heartbeat_seconds * 0.15))
        await asyncio.sleep(max(0.1, config.heartbeat_seconds + random.uniform(-jitter, jitter)))


async def command_loop(websocket: Any, config: AgentConfig, connection: dict[str, Any] | None = None) -> None:
    command_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    command_busy = asyncio.Event()
    cancel_event = threading.Event()
    connection = connection if connection is not None else {"session_id": None, "open": True}
    worker_task = asyncio.create_task(
        command_worker_loop(websocket, config, command_queue, command_busy, cancel_event, connection)
    )
    try:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            message_type = message.get("type")
            if message_type == "hello_ack":
                session_id = message.get("session_id")
                if isinstance(session_id, str) and session_id:
                    connection["session_id"] = session_id
                continue
            if message_type == "control" and message.get("action") == CONTROL_CANCEL_ACTIVE_COMMAND:
                cancel_event.set()
                continue
            if message_type != "command":
                continue
            command = message.get("command") or {}
            if command_busy.is_set() or not command_queue.empty():
                await websocket.send(json.dumps(result(command, "failure", COMMAND_BUSY_MESSAGE)))
                continue
            command.setdefault("agent_id", config.agent_id)
            if isinstance(connection.get("session_id"), str) and connection["session_id"]:
                command.setdefault("session_id", connection["session_id"])
            cancel_event.clear()
            command_queue.put_nowait(command)
    finally:
        connection["open"] = False
        cancel_event.set()
        if not command_busy.is_set():
            worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)


async def command_worker_loop(
    websocket: Any,
    config: AgentConfig,
    command_queue: asyncio.Queue[dict[str, Any]],
    command_busy: asyncio.Event,
    cancel_event: threading.Event,
    connection: dict[str, Any] | None = None,
) -> None:
    connection = connection if connection is not None else {"open": True}
    while True:
        command = await command_queue.get()
        command_busy.set()
        stop_after_command = False
        try:
            command_result = await dispatch_command_in_worker(command, config, cancel_event)
            if connection.get("open", True):
                await websocket.send(json.dumps(command_result))
        finally:
            command_busy.clear()
            cancel_event.clear()
            command_queue.task_done()
            stop_after_command = not connection.get("open", True)
        if stop_after_command:
            return


async def dispatch_command_in_worker(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(lambda: asyncio.run(dispatch_command_with_timeout(command, config, cancel_event)))


async def dispatch_command_with_timeout(
    command: dict[str, Any],
    config: AgentConfig,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    command_timeout = command.get("execution_timeout_seconds", config.command_timeout_seconds)
    if isinstance(command_timeout, bool) or not isinstance(command_timeout, (int, float)):
        command_timeout = config.command_timeout_seconds
    command_timeout = max(0.001, min(1800.0, float(command_timeout)))
    try:
        return await asyncio.wait_for(dispatch_command(command, config, cancel_event), timeout=command_timeout)
    except asyncio.TimeoutError:
        return result(command, "failure", f"Comando excedeu o tempo limite de {command_timeout:g}s.")


async def run_connection(websocket: Any, config: AgentConfig) -> None:
    connection: dict[str, Any] = {"session_id": None, "open": True}
    await websocket.send(json.dumps(hello_message(config)))
    heartbeat_task = asyncio.create_task(heartbeat_loop(websocket, config, connection))
    command_task = asyncio.create_task(command_loop(websocket, config, connection))
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
        connection["open"] = False
        remaining = [task for task in tasks if not task.done()]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)


async def run_agent(config: AgentConfig) -> None:
    import websockets

    url = build_agent_url(config)
    failures = 0
    while True:
        try:
            async with websockets.connect(
                url,
                additional_headers=connection_headers(config),
                ping_interval=config.websocket_ping_interval_seconds,
                ping_timeout=config.websocket_ping_timeout_seconds,
            ) as websocket:
                await run_connection(websocket, config)
                failures = 0
        except Exception as exc:
            failures += 1
            backoff = min(config.reconnect_max_seconds, config.reconnect_seconds * (2 ** min(failures - 1, 8)))
            jitter = random.uniform(0, min(1.0, backoff * 0.15))
            print(
                f"Agent connection failed ({type(exc).__name__}). Retrying in {backoff + jitter:g}s.",
                flush=True,
            )
            await asyncio.sleep(backoff + jitter)
            continue
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
