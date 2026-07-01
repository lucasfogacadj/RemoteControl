from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .domain import default_settings, validate_settings


ACTIVE_COMMAND_STATUSES = ("queued", "pending", "dispatched")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._lock = threading.Lock()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_state (
                    agent_id TEXT PRIMARY KEY,
                    online INTEGER NOT NULL,
                    last_heartbeat TEXT,
                    last_message TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    routine TEXT,
                    message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_message TEXT
                );
                """
            )
            exists = self._conn.execute("SELECT 1 FROM settings WHERE id = 1").fetchone()
            if not exists:
                now = utc_now()
                self._conn.execute(
                    "INSERT INTO settings (id, data, updated_at) VALUES (1, ?, ?)",
                    (json.dumps(default_settings()), now),
                )
                self._conn.execute(
                    "INSERT INTO events (created_at, kind, status, routine, message) VALUES (?, ?, ?, ?, ?)",
                    (now, "system", "ok", None, "Hub inicializado com configuracao padrao."),
                )
            self._conn.commit()

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
            if not row:
                return default_settings()
            return validate_settings(json.loads(row["data"]))

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        validated = validate_settings(settings)
        with self._lock:
            self._conn.execute(
                "UPDATE settings SET data = ?, updated_at = ? WHERE id = 1",
                (json.dumps(validated), utc_now()),
            )
            self._conn.commit()
        return validated

    def record_event(
        self,
        kind: str,
        status: str,
        message: str,
        routine: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (created_at, kind, status, routine, message) VALUES (?, ?, ?, ?, ?)",
                (utc_now(), kind, status, routine, message),
            )
            self._conn.commit()

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, kind, status, routine, message FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def touch_agent(self, agent_id: str, message: str = "heartbeat") -> None:
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agent_state (agent_id, online, last_heartbeat, last_message)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    online = 1,
                    last_heartbeat = excluded.last_heartbeat,
                    last_message = excluded.last_message
                """,
                (agent_id, now, message),
            )
            self._conn.commit()

    def set_agent_offline(self, agent_id: str, message: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agent_state (agent_id, online, last_heartbeat, last_message)
                VALUES (?, 0, NULL, ?)
                ON CONFLICT(agent_id) DO UPDATE SET online = 0, last_message = excluded.last_message
                """,
                (agent_id, message),
            )
            self._conn.commit()

    def get_agent_state(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT agent_id, online, last_heartbeat, last_message FROM agent_state ORDER BY last_heartbeat DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {
                "agent_id": None,
                "online": False,
                "last_heartbeat": None,
                "last_message": "Nenhum agente conectado.",
            }
        data = dict(row)
        data["online"] = bool(data["online"])
        return data

    def create_command(self, command_id: str, command: dict[str, Any], status: str = "dispatched") -> None:
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO commands (id, type, status, payload, created_at, updated_at, result_message)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (command_id, command["type"], status, json.dumps(command), now, now),
            )
            self._conn.commit()

    def mark_command_dispatched(self, command_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE commands SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                ("dispatched", utc_now(), command_id, "queued"),
            )
            self._conn.commit()

    def mark_command_result(self, command_id: str, status: str, message: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE commands SET status = ?, updated_at = ?, result_message = ? WHERE id = ?",
                (status, utc_now(), message, command_id),
            )
            self._conn.commit()

    def cancel_pending_commands(self) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE commands SET status = ?, updated_at = ?, result_message = ? WHERE status IN ('pending', 'queued')",
                ("cancelled", utc_now(), "Automacao desativada antes do envio."),
            )
            self._conn.commit()
            return cursor.rowcount

    def timeout_stale_commands(self, timeout_seconds: float) -> list[dict[str, Any]]:
        cutoff = (datetime.now(UTC) - timedelta(seconds=timeout_seconds)).isoformat()
        message = f"Comando sem resposta do agente por mais de {timeout_seconds:g}s."
        placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, type, status, payload, created_at, updated_at, result_message
                FROM commands
                WHERE status IN ({placeholders}) AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (*ACTIVE_COMMAND_STATUSES, cutoff),
            ).fetchall()
            if rows:
                ids = [row["id"] for row in rows]
                id_placeholders = ",".join("?" for _ in ids)
                self._conn.execute(
                    f"""
                    UPDATE commands
                    SET status = ?, updated_at = ?, result_message = ?
                    WHERE id IN ({id_placeholders})
                    """,
                    ("timeout", utc_now(), message, *ids),
                )
                self._conn.commit()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            item["timeout_message"] = message
            output.append(item)
        return output

    def get_active_command(self) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT id, type, status, payload, created_at, updated_at, result_message
                FROM commands
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT 1
                """,
                ACTIVE_COMMAND_STATUSES,
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        return item

    def list_commands(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, type, status, payload, created_at, updated_at, result_message FROM commands ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            output.append(item)
        return output
