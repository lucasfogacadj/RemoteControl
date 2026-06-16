from __future__ import annotations

import asyncio
import random
import time
from typing import Any
from uuid import uuid4

from .agent_manager import AgentManager
from .domain import SettingsError, build_command, choose_routine
from .store import Store


class RoutineScheduler:
    def __init__(self, store: Store, agent_manager: AgentManager, tick_seconds: float = 1.0):
        self.store = store
        self.agent_manager = agent_manager
        self.tick_seconds = tick_seconds
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

        settings = self.store.get_settings()
        if not settings.get("enabled"):
            self._next_run_at = now + 2
            return

        if not self.agent_manager.is_connected():
            self.store.record_event("scheduler", "skipped", "Nenhum agente conectado para receber comando.")
            self._next_run_at = now + 10
            return

        try:
            routine = choose_routine(settings)
            command = build_command(routine, settings)
        except SettingsError as exc:
            self.store.record_event("scheduler", "error", str(exc))
            self._next_run_at = now + 10
            return

        command_id = str(uuid4())
        command["id"] = command_id
        sent = await self.agent_manager.send_command(command)
        if sent:
            self.store.create_command(command_id, command)
            self.store.record_event(
                "command",
                "dispatched",
                f"Comando enviado: {command['type']}",
                routine=command["type"],
            )
        else:
            self.store.record_event("scheduler", "skipped", "Agente desconectou antes do envio.")

        minimum = int(settings["min_interval_seconds"])
        maximum = int(settings["max_interval_seconds"])
        self._next_run_at = now + random.uniform(minimum, maximum)
