from dataclasses import dataclass
import os


@dataclass(frozen=True)
class HubConfig:
    database_path: str
    pairing_token: str
    scheduler_tick_seconds: float
    agent_heartbeat_timeout_seconds: float
    command_timeout_seconds: float
    sentry_dsn: str
    sentry_environment: str
    sentry_release: str
    sentry_traces_sample_rate: float
    sentry_send_default_pii: bool


def env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def env_float_between(name: str, default: float, minimum: float, maximum: float) -> float:
    return min(maximum, env_float(name, default, minimum))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> HubConfig:
    return HubConfig(
        database_path=os.getenv("CONTROL_DB_PATH", "hub/data/control.db"),
        pairing_token=os.getenv("CONTROL_PAIRING_TOKEN", "dev-change-me"),
        scheduler_tick_seconds=env_float("CONTROL_SCHEDULER_TICK_SECONDS", 1, 0.1),
        agent_heartbeat_timeout_seconds=env_float("CONTROL_AGENT_HEARTBEAT_TIMEOUT_SECONDS", 45, 5),
        command_timeout_seconds=env_float("CONTROL_COMMAND_TIMEOUT_SECONDS", 120, 5),
        sentry_dsn=os.getenv("CONTROL_SENTRY_DSN", os.getenv("SENTRY_DSN", "")).strip(),
        sentry_environment=os.getenv("CONTROL_SENTRY_ENVIRONMENT", os.getenv("SENTRY_ENVIRONMENT", "production")).strip(),
        sentry_release=os.getenv("CONTROL_SENTRY_RELEASE", os.getenv("SENTRY_RELEASE", "")).strip(),
        sentry_traces_sample_rate=env_float_between("CONTROL_SENTRY_TRACES_SAMPLE_RATE", 0.0, 0.0, 1.0),
        sentry_send_default_pii=env_bool("CONTROL_SENTRY_SEND_DEFAULT_PII", False),
    )
