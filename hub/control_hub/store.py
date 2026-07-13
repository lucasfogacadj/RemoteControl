from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .domain import SettingsError, default_settings, validate_settings


LEGACY_AGENT_ID = "windows-desktop-01"
MIGRATION_VERSION_MULTI_PC = 1
ACTIVE_COMMAND_STATUSES = ("queued", "pending", "dispatched", "running")
TERMINAL_COMMAND_STATUSES = ("success", "failure", "cancelled", "timeout")
KNOWN_COMMAND_STATUSES = set(ACTIVE_COMMAND_STATUSES) | set(TERMINAL_COMMAND_STATUSES)
KNOWN_RESULT_STATUSES = {"success", "failure", "cancelled"}


class RevisionConflict(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(f"Configuracao foi alterada; revisao atual: {current_revision}.")


class ActiveCommandConflict(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _cursor_encode(created_at: str, row_id: int | str) -> str:
    raw = json.dumps([created_at, str(row_id)], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        created_at, row_id = json.loads(raw.decode("utf-8"))
        if not isinstance(created_at, str) or not isinstance(row_id, str):
            raise ValueError
        _parse_iso(created_at)
        return created_at, row_id
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cursor invalido.") from exc


class Store:
    """SQLite persistence with a compatibility adapter for the former singleton API."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        self._lock = threading.RLock()
        self._closed = False
        self._transition_states: dict[tuple[str | None, str], str] = {}
        self.last_backup_path: str | None = None
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")

    # -- bootstrap, backup and migration -------------------------------------------------
    def init(self) -> None:
        with self._lock:
            self._assert_open()
            self._create_legacy_schema_locked()
            self._ensure_legacy_settings_locked()
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            migrated = self._conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION_MULTI_PC,)
            ).fetchone()
            if not migrated:
                self._backup_and_verify_locked()
                self._migrate_multi_pc_locked()
            self._conn.execute("UPDATE agent_state SET online = 0, session_id = NULL WHERE online != 0 OR session_id IS NOT NULL")
            self._conn.commit()

    def _create_legacy_schema_locked(self) -> None:
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
            CREATE INDEX IF NOT EXISTS idx_commands_created_at ON commands(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_commands_status_created_at ON commands(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_commands_status_updated_at ON commands(status, updated_at);
            """
        )

    def _ensure_legacy_settings_locked(self) -> None:
        row = self._conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
        if row:
            return
        settings = default_settings()
        now = utc_now()
        self._conn.execute(
            "INSERT INTO settings (id, data, updated_at) VALUES (1, ?, ?)",
            (json.dumps(settings, separators=(",", ":")), now),
        )
        self._conn.execute(
            "INSERT INTO events (created_at, kind, status, routine, message) VALUES (?, ?, ?, ?, ?)",
            (now, "system", "ok", None, "Hub inicializado com configuracao padrao."),
        )
        self._conn.commit()

    def _backup_and_verify_locked(self) -> None:
        if self.integrity_check_locked() != "ok":
            raise RuntimeError("SQLite integrity_check falhou antes da migracao.")
        source = Path(self.database_path)
        backup = source.with_name(f"{source.stem}.pre-multi-pc-v1.bak{source.suffix}")
        if not backup.exists():
            destination = sqlite3.connect(backup)
            try:
                self._conn.backup(destination)
            finally:
                destination.close()
        backup_conn = sqlite3.connect(backup)
        try:
            result = backup_conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            backup_conn.close()
        if result != "ok":
            raise RuntimeError("Backup SQLite falhou no integrity_check.")
        self.last_backup_path = str(backup)

    def backup(self, destination: str | None = None) -> str:
        with self._lock:
            self._assert_open()
            source = Path(self.database_path)
            target = Path(destination) if destination else source.with_name(
                f"{source.stem}.backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}{source.suffix}"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            backup_conn = sqlite3.connect(target)
            try:
                self._conn.backup(backup_conn)
                result = backup_conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                backup_conn.close()
            if result != "ok":
                raise RuntimeError("Backup SQLite falhou no integrity_check.")
            self.last_backup_path = str(target)
            return str(target)

    def integrity_check_locked(self) -> str:
        return str(self._conn.execute("PRAGMA integrity_check").fetchone()[0])

    def integrity_check(self) -> str:
        with self._lock:
            self._assert_open()
            return self.integrity_check_locked()

    def _column_names_locked(self, table: str) -> set[str]:
        return {str(row["name"]) for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _add_column_locked(self, table: str, column: str, declaration: str) -> None:
        if column not in self._column_names_locked(table):
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _migrate_multi_pc_locked(self) -> None:
        now = utc_now()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fleet_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_settings (
                    agent_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._add_column_locked("agent_state", "session_id", "TEXT")
            self._add_column_locked("agent_state", "name", "TEXT")
            self._add_column_locked("agent_state", "version", "TEXT")
            self._add_column_locked("agent_state", "protocol", "TEXT")
            self._add_column_locked("agent_state", "dry_run", "INTEGER")
            self._add_column_locked("agent_state", "capabilities", "TEXT")
            self._add_column_locked("agent_state", "updated_at", "TEXT")
            self._add_column_locked("commands", "agent_id", "TEXT")
            self._add_column_locked("commands", "session_id", "TEXT")
            self._add_column_locked("commands", "deadline_at", "TEXT")
            self._add_column_locked("events", "agent_id", "TEXT")
            self._add_column_locked("events", "command_id", "TEXT")

            legacy_row = self._conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
            try:
                raw_legacy_settings = json.loads(legacy_row["data"]) if legacy_row else default_settings()
                # Older installations could have enabled the singleton before a
                # VS Code target was configured. Preserve the activation bit in the
                # dedicated column while normalizing the JSON document safely.
                legacy_enabled = raw_legacy_settings.get("enabled", False) if isinstance(raw_legacy_settings, dict) else False
                if isinstance(raw_legacy_settings, dict):
                    raw_legacy_settings = dict(raw_legacy_settings)
                    raw_legacy_settings["enabled"] = False
                legacy_settings = validate_settings(raw_legacy_settings)
            except (SettingsError, json.JSONDecodeError):
                legacy_settings = default_settings()
                legacy_enabled = False
            legacy_enabled = int(legacy_enabled is True)
            self._conn.execute(
                "INSERT OR IGNORE INTO fleet_state (id, enabled, updated_at) VALUES (1, 0, ?)", (now,)
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO agent_settings (agent_id, enabled, data, revision, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (LEGACY_AGENT_ID, legacy_enabled, json.dumps(legacy_settings, separators=(",", ":")), now, now),
            )
            placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
            self._conn.execute(
                f"""
                UPDATE commands
                SET status = 'cancelled', updated_at = ?, result_message = COALESCE(result_message, ?)
                WHERE agent_id IS NULL AND status IN ({placeholders})
                """,
                (now, "Comando legado cancelado durante a migracao multi-PC.", *ACTIVE_COMMAND_STATUSES),
            )
            for statement in (
                "CREATE INDEX IF NOT EXISTS idx_agent_settings_updated_at ON agent_settings(updated_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_agent_state_heartbeat ON agent_state(last_heartbeat DESC)",
                "CREATE INDEX IF NOT EXISTS idx_commands_agent_status_created ON commands(agent_id, status, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_commands_agent_updated ON commands(agent_id, updated_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_events_agent_created ON events(agent_id, created_at DESC, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_events_command_id ON events(command_id)",
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_command_per_agent
                    ON commands(agent_id)
                    WHERE agent_id IS NOT NULL AND status IN ('queued', 'pending', 'dispatched', 'running')
                """,
            ):
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (MIGRATION_VERSION_MULTI_PC, now),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Store SQLite ja foi fechado.")

    # -- fleet and agent settings ---------------------------------------------------------
    def ensure_agent(self, agent_id: str, *, enabled: bool = False) -> bool:
        now = utc_now()
        with self._lock:
            self._assert_open()
            existing = self._conn.execute("SELECT 1 FROM agent_settings WHERE agent_id = ?", (agent_id,)).fetchone()
            if existing:
                return False
            settings = default_settings()
            settings["enabled"] = enabled
            self._conn.execute(
                """
                INSERT INTO agent_settings (agent_id, enabled, data, revision, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (agent_id, int(enabled), json.dumps(settings, separators=(",", ":")), now, now),
            )
            self._conn.execute(
                """
                INSERT INTO agent_state (agent_id, online, last_heartbeat, last_message, updated_at)
                VALUES (?, 0, NULL, ?, ?)
                ON CONFLICT(agent_id) DO NOTHING
                """,
                (agent_id, "Aguardando conexao.", now),
            )
            self._conn.commit()
            return True

    def get_fleet_state(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT enabled, updated_at FROM fleet_state WHERE id = 1").fetchone()
            if not row:
                return {"enabled": True, "updated_at": None}
            return {"enabled": bool(row["enabled"]), "updated_at": row["updated_at"]}

    def set_fleet_enabled(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise SettingsError("enabled deve ser booleano verdadeiro ou falso.")
        now = utc_now()
        with self._lock:
            self._conn.execute(
                "UPDATE fleet_state SET enabled = ?, updated_at = ? WHERE id = 1", (int(enabled), now)
            )
            self._conn.commit()
        return self.get_fleet_state()

    def _agent_config_locked(self, agent_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT agent_id, enabled, data, revision, created_at, updated_at FROM agent_settings WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        if not row:
            return None
        try:
            settings = validate_settings(json.loads(row["data"]))
        except (SettingsError, json.JSONDecodeError):
            settings = default_settings()
        settings["enabled"] = bool(row["enabled"])
        return {
            "agent_id": row["agent_id"],
            "enabled": bool(row["enabled"]),
            "settings": settings,
            "revision": int(row["revision"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_agent_config(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._agent_config_locked(agent_id)

    def get_settings(self, agent_id: str = LEGACY_AGENT_ID) -> dict[str, Any]:
        with self._lock:
            config = self._agent_config_locked(agent_id)
            if config is None:
                self.ensure_agent(agent_id, enabled=False)
                config = self._agent_config_locked(agent_id)
            assert config is not None
            return deepcopy(config["settings"])

    def save_agent_settings(
        self,
        agent_id: str,
        settings: dict[str, Any],
        *,
        expected_revision: int | None = None,
        preserve_enabled: bool = True,
    ) -> dict[str, Any]:
        validated = validate_settings(settings)
        with self._lock:
            if self._agent_config_locked(agent_id) is None:
                self.ensure_agent(agent_id, enabled=False)
            current = self._agent_config_locked(agent_id)
            assert current is not None
            if expected_revision is not None and expected_revision != current["revision"]:
                raise RevisionConflict(current["revision"])
            enabled = current["enabled"] if preserve_enabled else validated["enabled"]
            validated["enabled"] = enabled
            now = utc_now()
            revision = current["revision"] + 1
            self._conn.execute(
                """
                UPDATE agent_settings
                SET enabled = ?, data = ?, revision = ?, updated_at = ?
                WHERE agent_id = ? AND revision = ?
                """,
                (int(enabled), json.dumps(validated, separators=(",", ":")), revision, now, agent_id, current["revision"]),
            )
            if agent_id == LEGACY_AGENT_ID:
                self._conn.execute(
                    "UPDATE settings SET data = ?, updated_at = ? WHERE id = 1",
                    (json.dumps(validated, separators=(",", ":")), now),
                )
            self._conn.commit()
            saved = self._agent_config_locked(agent_id)
            assert saved is not None
            return saved

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Legacy singleton adapter. New API callers use save_agent_settings."""
        return self.save_agent_settings(LEGACY_AGENT_ID, settings, preserve_enabled=False)["settings"]

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise SettingsError("enabled deve ser booleano verdadeiro ou falso.")
        with self._lock:
            if self._agent_config_locked(agent_id) is None:
                self.ensure_agent(agent_id, enabled=False)
            self._conn.execute("UPDATE agent_settings SET enabled = ? WHERE agent_id = ?", (int(enabled), agent_id))
            self._conn.commit()
            config = self._agent_config_locked(agent_id)
            assert config is not None
            return config

    # -- agent metadata ------------------------------------------------------------------
    def touch_agent(
        self,
        agent_id: str,
        message: str = "heartbeat",
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata = metadata or {}
        now = utc_now()
        with self._lock:
            if self._agent_config_locked(agent_id) is None:
                self.ensure_agent(agent_id, enabled=False)
            self._conn.execute(
                """
                INSERT INTO agent_state (
                    agent_id, online, last_heartbeat, last_message, session_id, name, version,
                    protocol, dry_run, capabilities, updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    online = 1,
                    last_heartbeat = excluded.last_heartbeat,
                    last_message = excluded.last_message,
                    session_id = COALESCE(excluded.session_id, agent_state.session_id),
                    name = COALESCE(excluded.name, agent_state.name),
                    version = COALESCE(excluded.version, agent_state.version),
                    protocol = COALESCE(excluded.protocol, agent_state.protocol),
                    dry_run = COALESCE(excluded.dry_run, agent_state.dry_run),
                    capabilities = COALESCE(excluded.capabilities, agent_state.capabilities),
                    updated_at = excluded.updated_at
                """,
                (
                    agent_id,
                    now,
                    message,
                    session_id,
                    metadata.get("name"),
                    metadata.get("version"),
                    metadata.get("protocol"),
                    int(metadata["dry_run"]) if isinstance(metadata.get("dry_run"), bool) else None,
                    json.dumps(metadata["capabilities"]) if isinstance(metadata.get("capabilities"), list) else None,
                    now,
                ),
            )
            self._conn.commit()

    def set_agent_offline(self, agent_id: str, message: str) -> None:
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agent_state (agent_id, online, last_heartbeat, last_message, updated_at)
                VALUES (?, 0, NULL, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    online = 0, session_id = NULL, last_message = excluded.last_message, updated_at = excluded.updated_at
                """,
                (agent_id, message, now),
            )
            self._conn.commit()

    def mark_all_agents_offline(self, message: str = "hub startup") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE agent_state SET online = 0, session_id = NULL, last_message = ?, updated_at = ?",
                (message, utc_now()),
            )
            self._conn.commit()

    def _row_agent_state(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if not row:
            return {
                "agent_id": None,
                "online": False,
                "last_heartbeat": None,
                "last_message": "Nenhum agente conectado.",
                "session_id": None,
                "name": None,
                "version": None,
                "protocol": None,
                "dry_run": None,
                "capabilities": [],
            }
        output = dict(row)
        output["online"] = bool(output["online"])
        output["dry_run"] = bool(output["dry_run"]) if output.get("dry_run") is not None else None
        try:
            output["capabilities"] = json.loads(output.get("capabilities") or "[]")
        except json.JSONDecodeError:
            output["capabilities"] = []
        return output

    def get_agent_state(self, agent_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if agent_id is None:
                row = self._conn.execute(
                    "SELECT * FROM agent_state ORDER BY last_heartbeat DESC, updated_at DESC LIMIT 1"
                ).fetchone()
            else:
                row = self._conn.execute("SELECT * FROM agent_state WHERE agent_id = ?", (agent_id,)).fetchone()
            state = self._row_agent_state(row)
            if row is None and agent_id is not None:
                state["agent_id"] = agent_id
                state["last_message"] = "Aguardando conexao."
            return state

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.agent_id, s.enabled, s.revision, s.created_at AS settings_created_at,
                       s.updated_at AS settings_updated_at, a.online, a.last_heartbeat, a.last_message,
                       a.session_id, a.name, a.version, a.protocol, a.dry_run, a.capabilities
                FROM agent_settings s
                LEFT JOIN agent_state a ON a.agent_id = s.agent_id
                ORDER BY s.agent_id ASC
                """
            ).fetchall()
            agents = []
            for row in rows:
                data = dict(row)
                data["enabled"] = bool(data["enabled"])
                data["online"] = bool(data["online"]) if data["online"] is not None else False
                data["dry_run"] = bool(data["dry_run"]) if data.get("dry_run") is not None else None
                try:
                    data["capabilities"] = json.loads(data.get("capabilities") or "[]")
                except json.JSONDecodeError:
                    data["capabilities"] = []
                active = self._get_active_command_locked(data["agent_id"])
                data["active_command"] = active
                agents.append(data)
            return agents

    # -- event history -------------------------------------------------------------------
    def record_event(
        self,
        kind: str,
        status: str,
        message: str,
        routine: str | None = None,
        *,
        agent_id: str | None = None,
        command_id: str | None = None,
    ) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO events (created_at, kind, status, routine, message, agent_id, command_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now(), kind, status, routine, message, agent_id, command_id),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def record_transition(
        self,
        agent_id: str | None,
        key: str,
        status: str,
        message: str,
        *,
        kind: str = "scheduler",
        routine: str | None = None,
    ) -> bool:
        with self._lock:
            transition_key = (agent_id, key)
            state = f"{status}\x00{message}"
            if self._transition_states.get(transition_key) == state:
                return False
            self._transition_states[transition_key] = state
        self.record_event(kind, status, message, routine=routine, agent_id=agent_id)
        return True

    def _events_query_locked(
        self, limit: int, agent_id: str | None, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        decoded = _cursor_decode(cursor)
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if decoded:
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            params.extend((decoded[0], decoded[0], int(decoded[1])))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT id, created_at, kind, status, routine, message, agent_id, command_id
            FROM events {where}
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (*params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        output = []
        for row in rows:
            item = dict(row)
            item["legacy_unassigned"] = item["agent_id"] is None
            output.append(item)
        next_cursor = _cursor_encode(rows[-1]["created_at"], rows[-1]["id"]) if has_more and rows else None
        return output, next_cursor

    def list_events(self, limit: int = 50, agent_id: str | None = None, cursor: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows, _ = self._events_query_locked(limit, agent_id, cursor)
            return rows

    def list_events_page(self, *, limit: int = 50, agent_id: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        with self._lock:
            rows, next_cursor = self._events_query_locked(limit, agent_id, cursor)
            return {"items": rows, "next_cursor": next_cursor}

    # -- command lifecycle ---------------------------------------------------------------
    def create_command(
        self,
        command_id: str,
        command: dict[str, Any],
        status: str = "dispatched",
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        deadline_at: str | None = None,
    ) -> None:
        if status not in KNOWN_COMMAND_STATUSES:
            raise ValueError("Status de comando desconhecido.")
        now = utc_now()
        payload = deepcopy(command)
        payload.setdefault("id", command_id)
        if agent_id is not None:
            payload.setdefault("agent_id", agent_id)
        if session_id is not None:
            payload.setdefault("session_id", session_id)
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO commands (
                        id, type, status, payload, created_at, updated_at, result_message,
                        agent_id, session_id, deadline_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        command_id,
                        str(command["type"]),
                        status,
                        json.dumps(payload, separators=(",", ":")),
                        now,
                        now,
                        agent_id,
                        session_id,
                        deadline_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if agent_id is not None and (
                    "idx_one_active_command_per_agent" in str(exc) or "commands.agent_id" in str(exc)
                ):
                    raise ActiveCommandConflict(f"Agente {agent_id} ja possui comando ativo.") from exc
                raise
            self._conn.commit()

    def _ownership_clause(
        self, agent_id: str | None, session_id: str | None, params: list[Any]
    ) -> str:
        clauses = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        return f" AND {' AND '.join(clauses)}" if clauses else ""

    def mark_command_dispatched(
        self, command_id: str, *, agent_id: str | None = None, session_id: str | None = None
    ) -> bool:
        with self._lock:
            params: list[Any] = ["dispatched", utc_now(), command_id, "queued"]
            ownership = self._ownership_clause(agent_id, session_id, params)
            cursor = self._conn.execute(
                f"UPDATE commands SET status = ?, updated_at = ? WHERE id = ? AND status = ?{ownership}", params
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def mark_command_running(
        self, command_id: str, *, agent_id: str | None = None, session_id: str | None = None
    ) -> bool:
        with self._lock:
            params: list[Any] = ["running", utc_now(), command_id, "dispatched"]
            ownership = self._ownership_clause(agent_id, session_id, params)
            cursor = self._conn.execute(
                f"UPDATE commands SET status = ?, updated_at = ? WHERE id = ? AND status = ?{ownership}", params
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def mark_command_result(
        self,
        command_id: str,
        status: str,
        message: str,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        if status not in KNOWN_RESULT_STATUSES:
            return False
        placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
        with self._lock:
            params: list[Any] = [status, utc_now(), message, command_id, *ACTIVE_COMMAND_STATUSES]
            ownership = self._ownership_clause(agent_id, session_id, params)
            cursor = self._conn.execute(
                f"""
                UPDATE commands SET status = ?, updated_at = ?, result_message = ?
                WHERE id = ? AND status IN ({placeholders}){ownership}
                """,
                params,
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def cancel_active_commands(
        self,
        message: str = "Automacao desativada antes da conclusao.",
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
        with self._lock:
            params: list[Any] = ["cancelled", utc_now(), message, *ACTIVE_COMMAND_STATUSES]
            ownership = self._ownership_clause(agent_id, session_id, params)
            cursor = self._conn.execute(
                f"UPDATE commands SET status = ?, updated_at = ?, result_message = ? WHERE status IN ({placeholders}){ownership}",
                params,
            )
            self._conn.commit()
            return cursor.rowcount

    def cancel_pending_commands(self) -> int:
        return self.cancel_active_commands("Automacao desativada antes do envio.")

    def _row_command(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"])
        except (TypeError, json.JSONDecodeError):
            item["payload"] = {}
        item["legacy_unassigned"] = item.get("agent_id") is None
        return item

    def timeout_stale_commands(self, timeout_seconds: float | None = None) -> list[dict[str, Any]]:
        now = utc_now()
        fallback_timeout = 120.0 if timeout_seconds is None else timeout_seconds
        cutoff = (datetime.now(UTC) - timedelta(seconds=fallback_timeout)).isoformat()
        placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, type, status, payload, created_at, updated_at, result_message, agent_id, session_id, deadline_at
                FROM commands
                WHERE status IN ({placeholders})
                  AND ((deadline_at IS NOT NULL AND deadline_at <= ?) OR (deadline_at IS NULL AND updated_at < ?))
                ORDER BY COALESCE(deadline_at, updated_at) ASC
                """,
                (*ACTIVE_COMMAND_STATUSES, now, cutoff),
            ).fetchall()
            output = []
            for row in rows:
                deadline = row["deadline_at"]
                message = (
                    "Comando excedeu o deadline calculado pelo hub."
                    if deadline is not None
                    else f"Comando sem resposta do agente por mais de {fallback_timeout:g}s."
                )
                cursor = self._conn.execute(
                    f"UPDATE commands SET status = ?, updated_at = ?, result_message = ? WHERE id = ? AND status IN ({placeholders})",
                    ("timeout", now, message, row["id"], *ACTIVE_COMMAND_STATUSES),
                )
                if cursor.rowcount:
                    item = self._row_command(row)
                    assert item is not None
                    item["timeout_message"] = message
                    output.append(item)
            self._conn.commit()
            return output

    def _get_active_command_locked(self, agent_id: str | None = None) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in ACTIVE_COMMAND_STATUSES)
        where = "AND agent_id = ?" if agent_id is not None else ""
        params: tuple[Any, ...] = (*ACTIVE_COMMAND_STATUSES, agent_id) if agent_id is not None else ACTIVE_COMMAND_STATUSES
        row = self._conn.execute(
            f"""
            SELECT id, type, status, payload, created_at, updated_at, result_message, agent_id, session_id, deadline_at
            FROM commands WHERE status IN ({placeholders}) {where}
            ORDER BY created_at ASC LIMIT 1
            """,
            params,
        ).fetchone()
        return self._row_command(row)

    def get_active_command(self, agent_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            return self._get_active_command_locked(agent_id)

    def _commands_query_locked(
        self, limit: int, agent_id: str | None, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        decoded = _cursor_decode(cursor)
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if decoded:
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            params.extend((decoded[0], decoded[0], decoded[1]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT id, type, status, payload, created_at, updated_at, result_message, agent_id, session_id, deadline_at
            FROM commands {where} ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (*params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        output = [self._row_command(row) for row in rows]
        next_cursor = _cursor_encode(rows[-1]["created_at"], rows[-1]["id"]) if has_more and rows else None
        return [item for item in output if item is not None], next_cursor

    def list_commands(self, limit: int = 20, agent_id: str | None = None, cursor: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows, _ = self._commands_query_locked(limit, agent_id, cursor)
            return rows

    def list_commands_page(self, *, limit: int = 20, agent_id: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        with self._lock:
            rows, next_cursor = self._commands_query_locked(limit, agent_id, cursor)
            return {"items": rows, "next_cursor": next_cursor}

    def cleanup_terminal(self, retention_days: int = 90, batch_size: int = 250) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self._lock:
            command_ids = self._conn.execute(
                f"""
                SELECT id FROM commands
                WHERE status IN ({','.join('?' for _ in TERMINAL_COMMAND_STATUSES)}) AND updated_at < ?
                ORDER BY updated_at ASC LIMIT ?
                """,
                (*TERMINAL_COMMAND_STATUSES, cutoff, batch_size),
            ).fetchall()
            event_ids = self._conn.execute(
                "SELECT id FROM events WHERE created_at < ? ORDER BY created_at ASC LIMIT ?", (cutoff, batch_size)
            ).fetchall()
            if command_ids:
                self._conn.execute(
                    f"DELETE FROM commands WHERE id IN ({','.join('?' for _ in command_ids)})",
                    tuple(row["id"] for row in command_ids),
                )
            if event_ids:
                self._conn.execute(
                    f"DELETE FROM events WHERE id IN ({','.join('?' for _ in event_ids)})",
                    tuple(row["id"] for row in event_ids),
                )
            self._conn.commit()
            return {"commands": len(command_ids), "events": len(event_ids)}

    # -- dashboard/API convenience -------------------------------------------------------
    def get_agent_snapshot(self, agent_id: str, events_limit: int = 50, commands_limit: int = 20) -> dict[str, Any] | None:
        with self._lock:
            config = self._agent_config_locked(agent_id)
            if config is None:
                return None
            return {
                "settings": deepcopy(config["settings"]),
                "settings_revision": config["revision"],
                "agent": self.get_agent_state(agent_id),
                "events": self.list_events(events_limit, agent_id=agent_id),
                "commands": self.list_commands(commands_limit, agent_id=agent_id),
                "active_command": self._get_active_command_locked(agent_id),
            }

    def get_state_snapshot(self, events_limit: int = 50, commands_limit: int = 20) -> dict[str, Any]:
        """Legacy dashboard snapshot fixed to the migrated legacy agent."""
        with self._lock:
            config = self._agent_config_locked(LEGACY_AGENT_ID)
            settings = deepcopy(config["settings"]) if config else default_settings()
            # Preserve the former Store-level dashboard behavior for direct legacy
            # callers. The HTTP /api/state alias does not use this helper and is
            # explicitly scoped to windows-desktop-01.
            agent = self.get_agent_state()
            return {
                "settings": settings,
                "agent": agent,
                # Preserve the former Store-level dashboard contract. The HTTP alias now
                # uses get_agent_snapshot and is explicitly scoped to the legacy agent.
                "events": self.list_events(events_limit),
                "commands": self.list_commands(commands_limit),
            }

    def readiness(self) -> dict[str, Any]:
        with self._lock:
            try:
                integrity = self.integrity_check_locked()
                migrated = self._conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION_MULTI_PC,)
                ).fetchone()
                return {"sqlite": integrity == "ok", "migration": bool(migrated), "integrity": integrity}
            except sqlite3.Error as exc:
                return {"sqlite": False, "migration": False, "integrity": str(exc)}
