from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

from .agent_manager import AgentManager
from .domain import SettingsError, build_command, choose_routine
from .observability import capture_exception
from .rhythm import RhythmEngine
from .store import Store


class RoutineScheduler:
    def __init__(
        self,
        store: Store,
        agent_manager: AgentManager,
        tick_seconds: float = 1.0,
        command_timeout_seconds: float = 120.0,
        rhythm_engine: RhythmEngine | None = None,
    ):
        self.store = store
        self.agent_manager = agent_manager
        self.tick_seconds = tick_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.rhythm_engine = rhythm_engine or RhythmEngine()
        self._stop_event = asyncio.Event()
        self._next_run_at = time.monotonic() + 2

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

    def stop(self) -> None:
        self._stop_event.set()

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": not self._stop_event.is_set(),
            "next_run_in_seconds": max(0, round(self._next_run_at - time.monotonic(), 2)),
        }

    async def _tick(self) -> None:
        now = time.monotonic()
        if now < self._next_run_at:
            return

        timed_out_commands = self.store.timeout_stale_commands(self.command_timeout_seconds)
        for command in timed_out_commands:
            self.store.record_event(
                "command",
                "timeout",
                command["timeout_message"],
                routine=command["type"],
            )

        settings = self.store.get_settings()
        if not settings.get("enabled"):
            self._next_run_at = now + 2
            return

        if self.store.get_active_command():
            self._next_run_at = now + max(1.0, self.tick_seconds)
            return

        if not self.agent_manager.is_connected():
            self.store.record_event("scheduler", "skipped", "Nenhum agente conectado para receber comando.")
            self._next_run_at = now + 10
            return

        try:
            rhythm_state = self.rhythm_engine.evaluate(settings)
            if rhythm_state.is_pause:
                self.store.record_event(
                    "scheduler",
                    "paused",
                    f"Pausa organica: {rhythm_state.pause_type} por {round(rhythm_state.pause_seconds)}s.",
                )
                self._next_run_at = now + rhythm_state.next_interval_seconds(settings)
                return

            routine = choose_routine(settings, routine_multipliers=rhythm_state.routine_multipliers)
            command = build_command(
                routine,
                settings,
                context={"energy": rhythm_state.energy, "mode": rhythm_state.mode},
            )
        except SettingsError as exc:
            self.store.record_event("scheduler", "error", str(exc))
            self._next_run_at = now + 10
            return

        command_id = str(uuid4())
        command["id"] = command_id
        self.store.create_command(command_id, command, status="queued")
        sent = await self.agent_manager.send_command(command)
        if sent:
            self.store.mark_command_dispatched(command_id)
            self.store.record_event(
                "command",
                "dispatched",
                f"Comando enviado: {command['type']}",
                routine=command["type"],
            )
        else:
            message = "Agente desconectou antes do envio."
            self.store.mark_command_result(command_id, "failure", message)
            self.store.record_event("scheduler", "skipped", message)

        self._next_run_at = now + rhythm_state.next_interval_seconds(settings)
