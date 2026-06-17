from dataclasses import dataclass
import os


@dataclass(frozen=True)
class HubConfig:
    database_path: str
    pairing_token: str
    scheduler_tick_seconds: float
    agent_heartbeat_timeout_seconds: float


def env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def load_config() -> HubConfig:
    return HubConfig(
        database_path=os.getenv("CONTROL_DB_PATH", "hub/data/control.db"),
        pairing_token=os.getenv("CONTROL_PAIRING_TOKEN", "dev-change-me"),
        scheduler_tick_seconds=env_float("CONTROL_SCHEDULER_TICK_SECONDS", 1, 0.1),
        agent_heartbeat_timeout_seconds=env_float("CONTROL_AGENT_HEARTBEAT_TIMEOUT_SECONDS", 45, 5),
    )
