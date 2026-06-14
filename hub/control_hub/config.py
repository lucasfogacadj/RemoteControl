from dataclasses import dataclass
import os


@dataclass(frozen=True)
class HubConfig:
    database_path: str
    pairing_token: str
    scheduler_tick_seconds: float


def load_config() -> HubConfig:
    return HubConfig(
        database_path=os.getenv("CONTROL_DB_PATH", "hub/data/control.db"),
        pairing_token=os.getenv("CONTROL_PAIRING_TOKEN", "dev-change-me"),
        scheduler_tick_seconds=float(os.getenv("CONTROL_SCHEDULER_TICK_SECONDS", "1")),
    )

