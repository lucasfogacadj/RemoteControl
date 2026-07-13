from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time as dt_time, timedelta
import time
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from .agent_manager import AgentManager
from .contracts import LEGACY_AGENT_ID
from .domain import SettingsError, build_command, choose_routine, command_budgets
from .observability import capture_exception
from .rhythm import RhythmEngine
from .store import ActiveCommandConflict, Store, utc_now


@dataclass
class AgentScheduleRuntime:
    next_run_at: float
    rhythm_engine: RhythmEngine
    revision: int | None = None
    timezone: str | None = None
    blocked_state: str | None = None


class RoutineScheduler:
    """Single-process fleet scheduler with isolated runtime state per agent."""

    def __init__(
        self,
        store: Store,
        agent_manager: AgentManager,
        tick_seconds: float = 1.0,
        command_timeout_seconds: float = 120.0,
        rhythm_engine: RhythmEngine | None = None,
        now_provider: Callable[[ZoneInfo], datetime] | None = None,
    ) -> None:
        self.store = store
        self.agent_manager = agent_manager
        self.tick_seconds = tick_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self._legacy_rhythm_engine = rhythm_engine
        self._now_provider = now_provider or (lambda zone: datetime.now(zone))
        self._runtimes: dict[str, AgentScheduleRuntime] = {}
        self._stop_event = asyncio.Event()
        self._ensure_runtime(LEGACY_AGENT_ID, rhythm_engine=rhythm_engine)

    @property
    def _next_run_at(self) -> float:
        return self._ensure_runtime(LEGACY_AGENT_ID).next_run_at

    @_next_run_at.setter
    def _next_run_at(self, value: float) -> None:
        self._ensure_runtime(LEGACY_AGENT_ID).next_run_at = value

    def _new_rhythm_engine(self, timezone: str = "America/Sao_Paulo") -> RhythmEngine:
        zone = ZoneInfo(timezone)
        return RhythmEngine(now_provider=lambda: self._now_provider(zone))

    def _ensure_runtime(self, agent_id: str, rhythm_engine: RhythmEngine | None = None) -> AgentScheduleRuntime:
        runtime = self._runtimes.get(agent_id)
        if runtime is None:
            runtime = AgentScheduleRuntime(
                next_run_at=time.monotonic() + 2,
                rhythm_engine=rhythm_engine or self._legacy_rhythm_engine or self._new_rhythm_engine(),
            )
            self._runtimes[agent_id] = runtime
        return runtime

    def reset_agent(self, agent_id: str) -> None:
        runtime = self._runtimes.get(agent_id)
        if runtime is None:
            return
        runtime.rhythm_engine.reset()
        runtime.revision = None
        runtime.timezone = None
        runtime.next_run_at = time.monotonic() + 2
        runtime.blocked_state = None

    def stop(self) -> None:
        self._stop_event.set()

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        legacy = self._ensure_runtime(LEGACY_AGENT_ID)
        return {
            "running": not self._stop_event.is_set(),
            "next_run_in_seconds": max(0, round(legacy.next_run_at - now, 2)),
            "agents": {
                agent_id: {
                    "next_run_in_seconds": max(0, round(runtime.next_run_at - now, 2)),
                    "revision": runtime.revision,
                    "timezone": runtime.timezone,
                    "blocked_state": runtime.blocked_state,
                }
                for agent_id, runtime in self._runtimes.items()
            },
        }

    async def run(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self.tick_seconds)
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                capture_exception(exc)
                self.store.record_event("scheduler", "error", f"Scheduler recuperou apos erro: {exc}")
                self._next_run_at = time.monotonic() + 10

    async def _tick(self) -> None:
        # Housekeeping intentionally happens before every next_run gate.
        timed_out_commands = self.store.timeout_stale_commands(self.command_timeout_seconds)
        for command in timed_out_commands:
            agent_id = command.get("agent_id")
            self.store.record_event(
                "command",
                "timeout",
                command["timeout_message"],
                routine=command["type"],
                agent_id=agent_id,
                command_id=command["id"],
            )
            if agent_id:
                await self._cancel_agent_slot(agent_id, command.get("session_id"))

        fleet = self.store.get_fleet_state()
        agents = self.store.list_agents()
        if not agents:
            return
        now = time.monotonic()
        for agent in agents:
            await self._tick_agent(agent["agent_id"], fleet["enabled"], now)

        # Drop stale in-memory schedule state for deleted agents, keeping legacy intact.
        known = {agent["agent_id"] for agent in agents}
        for agent_id in list(self._runtimes):
            if agent_id not in known and agent_id != LEGACY_AGENT_ID:
                self._runtimes.pop(agent_id, None)

    async def _tick_agent(self, agent_id: str, fleet_enabled: bool, now: float) -> None:
        config = self.store.get_agent_config(agent_id)
        if config is None:
            return
        settings = config["settings"]
        runtime = self._ensure_runtime(agent_id)
        timezone = str(settings["timezone"])
        if runtime.timezone != timezone:
            runtime.rhythm_engine = self._legacy_rhythm_engine or self._new_rhythm_engine(timezone)
            runtime.timezone = timezone
            runtime.revision = config["revision"]
            runtime.next_run_at = min(runtime.next_run_at, now)
        elif runtime.revision is None:
            runtime.revision = config["revision"]
        elif runtime.revision != config["revision"]:
            runtime.rhythm_engine.reset()
            runtime.revision = config["revision"]
            runtime.next_run_at = now
            runtime.blocked_state = None

        if not fleet_enabled:
            await self._block_agent(agent_id, runtime, "fleet_off", "Frota pausada pelo master switch.")
            return
        if not config["enabled"]:
            await self._block_agent(agent_id, runtime, "agent_off", "PC desativado individualmente.")
            return
        if not self._inside_work_window(settings):
            await self._block_agent(agent_id, runtime, "outside_window", "PC fora da janela de trabalho.")
            return
        if not self._manager_is_connected(agent_id):
            runtime.next_run_at = now + 10
            if runtime.blocked_state != "offline":
                self.store.record_transition(
                    agent_id, "availability", "offline", "Nenhum agente conectado para receber comando."
                )
                runtime.blocked_state = "offline"
            return
        if runtime.blocked_state is not None:
            self.store.record_transition(agent_id, "availability", "ok", "Agente elegivel para agendamento.")
            runtime.blocked_state = None

        active = self.store.get_active_command(agent_id)
        # Compatibility: legacy commands from before migration have no agent_id and must
        # still block their migrated target until they are terminal.
        if active is None and agent_id == LEGACY_AGENT_ID:
            legacy_active = self.store.get_active_command()
            if legacy_active and legacy_active.get("agent_id") is None:
                active = legacy_active
        if active is not None or self._manager_has_active_execution(agent_id):
            runtime.next_run_at = now + max(1.0, self.tick_seconds)
            return
        if now < runtime.next_run_at:
            return

        try:
            rhythm_state = runtime.rhythm_engine.evaluate(settings)
            if rhythm_state.is_pause:
                self.store.record_transition(
                    agent_id,
                    "rhythm_pause",
                    "paused",
                    f"Pausa organica: {rhythm_state.pause_type} por {round(rhythm_state.pause_seconds)}s.",
                )
                runtime.next_run_at = now + rhythm_state.next_interval_seconds(settings)
                return
            routine = choose_routine(settings, routine_multipliers=rhythm_state.routine_multipliers)
            command = build_command(routine, settings, context={"energy": rhythm_state.energy, "mode": rhythm_state.mode})
        except SettingsError as exc:
            self.store.record_transition(agent_id, "settings_error", "error", str(exc))
            runtime.next_run_at = now + 10
            return

        session_id = self._manager_session_id(agent_id)
        command_id = str(uuid4())
        execution_budget, deadline_budget = command_budgets(command)
        if deadline_budget > 1800:
            self.store.record_transition(agent_id, "deadline", "error", "Comando excede o teto de 1800 segundos.")
            runtime.next_run_at = now + 10
            return
        deadline_at = (datetime.now(UTC) + timedelta(seconds=deadline_budget)).isoformat()
        command.update(
            {
                "id": command_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "execution_timeout_seconds": execution_budget,
                "deadline_at": deadline_at,
            }
        )
        try:
            self.store.create_command(
                command_id,
                command,
                status="queued",
                agent_id=agent_id,
                session_id=session_id,
                deadline_at=deadline_at,
            )
        except ActiveCommandConflict:
            runtime.next_run_at = now + max(1.0, self.tick_seconds)
            return

        sent = await self._manager_send_command(command, agent_id, session_id)
        if sent:
            self.store.mark_command_dispatched(command_id, agent_id=agent_id, session_id=session_id)
            self.store.record_event(
                "command",
                "dispatched",
                f"Comando enviado: {command['type']}",
                routine=command["type"],
                agent_id=agent_id,
                command_id=command_id,
            )
        else:
            message = "Agente desconectou antes do envio."
            self.store.mark_command_result(command_id, "failure", message, agent_id=agent_id, session_id=session_id)
            self.store.record_transition(agent_id, "availability", "offline", message)
        runtime.next_run_at = now + rhythm_state.next_interval_seconds(settings)

    async def _block_agent(self, agent_id: str, runtime: AgentScheduleRuntime, state: str, message: str) -> None:
        runtime.next_run_at = time.monotonic() + 2
        if runtime.blocked_state != state:
            self.store.record_transition(agent_id, "availability", "paused", message)
            runtime.blocked_state = state
        await self.cancel_agent(agent_id, message)

    async def cancel_agent(self, agent_id: str, message: str = "Automacao cancelada pelo hub.") -> int:
        active = self.store.get_active_command(agent_id)
        cancelled = self.store.cancel_active_commands(message, agent_id=agent_id)
        if cancelled:
            session_id = active.get("session_id") if active else self._manager_session_id(agent_id)
            await self._cancel_agent_slot(agent_id, session_id)
            self.store.record_event(
                "command", "cancelled", message, agent_id=agent_id, command_id=active.get("id") if active else None
            )
        return cancelled

    async def cancel_all(self, message: str = "Frota pausada pelo master switch.") -> int:
        total = 0
        for agent in self.store.list_agents():
            total += await self.cancel_agent(agent["agent_id"], message)
        return total

    def _inside_work_window(self, settings: dict[str, Any]) -> bool:
        zone = ZoneInfo(str(settings["timezone"]))
        now = self._now_provider(zone)
        start_hour, start_minute = (int(part) for part in str(settings["work_start"]).split(":"))
        end_hour, end_minute = (int(part) for part in str(settings["work_end"]).split(":"))
        start = datetime.combine(now.date(), dt_time(start_hour, start_minute), tzinfo=zone)
        end = datetime.combine(now.date(), dt_time(end_hour, end_minute), tzinfo=zone)
        return start <= now < end

    def _manager_is_connected(self, agent_id: str) -> bool:
        try:
            return bool(self.agent_manager.is_connected(agent_id))
        except TypeError:
            return bool(self.agent_manager.is_connected())

    def _manager_session_id(self, agent_id: str) -> str | None:
        getter = getattr(self.agent_manager, "get_session", None)
        if getter is None:
            return None
        session = getter(agent_id)
        return getattr(session, "session_id", None) if session is not None else None

    def _manager_has_active_execution(self, agent_id: str) -> bool:
        method = getattr(self.agent_manager, "has_active_execution", None)
        return bool(method(agent_id)) if method else False

    async def _manager_send_command(self, command: dict[str, Any], agent_id: str, session_id: str | None) -> bool:
        try:
            return bool(await self.agent_manager.send_command(command, agent_id=agent_id, session_id=session_id))
        except TypeError:
            return bool(await self.agent_manager.send_command(command))

    async def _cancel_agent_slot(self, agent_id: str, session_id: str | None) -> None:
        try:
            await self.agent_manager.cancel_active_command(agent_id=agent_id, session_id=session_id)
        except TypeError:
            await self.agent_manager.cancel_active_command()
