from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any
from uuid import uuid4

from fastapi import WebSocket


@dataclass
class AgentSession:
    agent_id: str
    websocket: WebSocket
    session_id: str
    generation: int
    last_seen_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class ExecutionSlot:
    command_id: str
    session_id: str
    cancel_requested: bool = False
    terminal: asyncio.Event = field(default_factory=asyncio.Event)


class AgentManager:
    """In-memory registry of independently connected agents and execution slots."""

    def __init__(self, heartbeat_timeout_seconds: float = 45.0) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._sessions: dict[str, AgentSession] = {}
        self._generations: dict[str, int] = {}
        self._slots: dict[str, ExecutionSlot] = {}

    # Compatibility properties retained for tests and older callers.
    @property
    def _agent_id(self) -> str | None:
        return next(iter(self._sessions), None)

    @property
    def _websocket(self) -> WebSocket | None:
        session = self._sessions.get(self._agent_id or "")
        return session.websocket if session else None

    @property
    def _last_seen_at(self) -> float | None:
        session = self._sessions.get(self._agent_id or "")
        return session.last_seen_at if session else None

    @_last_seen_at.setter
    def _last_seen_at(self, value: float | None) -> None:
        agent_id = self._agent_id
        if agent_id is not None and value is not None:
            self._sessions[agent_id].last_seen_at = value

    async def connect(
        self, agent_id: str, websocket: WebSocket, metadata: dict[str, Any] | None = None
    ) -> AgentSession:
        previous = self._sessions.get(agent_id)
        previous_slot = self._slots.get(agent_id)
        if previous is not None and previous_slot is not None and previous_slot.session_id == previous.session_id:
            previous_slot.cancel_requested = True
        generation = self._generations.get(agent_id, 0) + 1
        self._generations[agent_id] = generation
        session = AgentSession(
            agent_id=agent_id,
            websocket=websocket,
            session_id=str(uuid4()),
            generation=generation,
            last_seen_at=time.monotonic(),
            metadata=metadata or {},
        )
        self._sessions[agent_id] = session
        if previous is not None and previous.websocket is not websocket:
            try:
                await previous.websocket.close(code=4001)
            except Exception:
                pass
        # The agent only opens a fresh connection after its connection-owned worker
        # has completed cancellation. The explicit idle marker lets the hub release
        # a slot left by the broken socket without allowing concurrent execution.
        slot = self._slots.get(agent_id)
        if slot is not None and slot.cancel_requested and metadata and metadata.get("execution_idle") is True:
            self.release_execution(agent_id, command_id=slot.command_id, session_id=slot.session_id)
        return session

    async def disconnect(
        self, agent_id: str, websocket: WebSocket | None = None, session_id: str | None = None
    ) -> bool:
        session = self._sessions.get(agent_id)
        if session is None:
            return False
        if websocket is not None and session.websocket is not websocket:
            return False
        if session_id is not None and session.session_id != session_id:
            return False
        self._sessions.pop(agent_id, None)
        slot = self._slots.get(agent_id)
        if slot is not None:
            slot.cancel_requested = True
        return True

    async def record_heartbeat(
        self, agent_id: str, websocket: WebSocket | None = None, session_id: str | None = None
    ) -> bool:
        if not self.is_current_session(agent_id, websocket=websocket, session_id=session_id):
            return False
        session = self._sessions[agent_id]
        session.last_seen_at = time.monotonic()
        return True

    def is_current_session(
        self,
        agent_id: str,
        *,
        websocket: WebSocket | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Return whether a message still belongs to the live registry generation."""
        session = self._sessions.get(agent_id)
        if session is None:
            return False
        if websocket is not None and session.websocket is not websocket:
            return False
        if session_id is not None and session.session_id != session_id:
            return False
        return True

    def _is_stale(self, session: AgentSession, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        return moment - session.last_seen_at > self.heartbeat_timeout_seconds

    async def disconnect_stale(self) -> list[str]:
        stale = [session for session in list(self._sessions.values()) if self._is_stale(session)]
        disconnected: list[str] = []
        for session in stale:
            current = self._sessions.get(session.agent_id)
            if current is not session:
                continue
            self._sessions.pop(session.agent_id, None)
            slot = self._slots.get(session.agent_id)
            if slot is not None:
                slot.cancel_requested = True
            try:
                await session.websocket.close(code=4000)
            except Exception:
                pass
            disconnected.append(session.agent_id)
        return disconnected

    async def disconnect_if_stale(self) -> str | None:
        """Legacy single-result watchdog adapter."""
        stale = await self.disconnect_stale()
        return stale[0] if stale else None

    def is_connected(self, agent_id: str | None = None) -> bool:
        if agent_id is None:
            return any(not self._is_stale(session) for session in self._sessions.values())
        session = self._sessions.get(agent_id)
        return session is not None and not self._is_stale(session)

    def get_session(self, agent_id: str) -> AgentSession | None:
        session = self._sessions.get(agent_id)
        if session is not None and self._is_stale(session):
            return None
        return session

    def snapshot(self, agent_id: str | None = None) -> dict[str, Any]:
        # Preserve exactly the legacy no-argument shape.
        if agent_id is None:
            legacy_id = self._agent_id
            return {"connected": self.is_connected(), "agent_id": legacy_id if self.is_connected(legacy_id) else None}
        session = self.get_session(agent_id)
        if session is None:
            return {"connected": False, "agent_id": agent_id, "session_id": None, "generation": None}
        return {
            "connected": True,
            "agent_id": agent_id,
            "session_id": session.session_id,
            "generation": session.generation,
            "last_seen_monotonic": session.last_seen_at,
            "metadata": dict(session.metadata),
            "execution_active": self.has_active_execution(agent_id),
        }

    def fleet_snapshot(self) -> dict[str, dict[str, Any]]:
        return {agent_id: self.snapshot(agent_id) for agent_id in self._sessions}

    async def send_control(self, action: str, *, agent_id: str | None = None, session_id: str | None = None) -> bool:
        return await self._send_json({"type": "control", "action": action}, agent_id=agent_id, session_id=session_id)

    async def cancel_active_command(self, agent_id: str | None = None, session_id: str | None = None) -> bool:
        target = agent_id or self._agent_id
        if target is not None and target in self._slots:
            self._slots[target].cancel_requested = True
        return await self.send_control("cancel_active_command", agent_id=target, session_id=session_id)

    async def send_command(
        self, command: dict[str, Any], *, agent_id: str | None = None, session_id: str | None = None
    ) -> bool:
        target = agent_id or self._agent_id
        if target is None:
            return False
        session = self.get_session(target)
        if session is None or (session_id is not None and session.session_id != session_id):
            return False
        command_id = str(command.get("id", ""))
        if not command_id:
            # Compatibility for pre-session callers/tests. New scheduler commands always
            # carry an ID and therefore reserve the per-agent execution slot below.
            return await self._send_json({"type": "command", "command": command}, agent_id=target, session_id=session.session_id)
        if self.has_active_execution(target):
            return False
        self._slots[target] = ExecutionSlot(command_id=command_id, session_id=session.session_id)
        envelope = {"type": "command", "command": command}
        sent = await self._send_json(envelope, agent_id=target, session_id=session.session_id)
        if not sent:
            self.release_execution(target, command_id=command_id, session_id=session.session_id)
        return sent

    async def _send_json(self, payload: dict[str, Any], *, agent_id: str | None, session_id: str | None = None) -> bool:
        target = agent_id or self._agent_id
        if target is None:
            return False
        session = self.get_session(target)
        if session is None or (session_id is not None and session.session_id != session_id):
            return False
        async with session.send_lock:
            # A reconnect could have changed the registry while waiting for the lock.
            if self._sessions.get(target) is not session:
                return False
            try:
                await session.websocket.send_json(payload)
            except Exception:
                if self._sessions.get(target) is session:
                    self._sessions.pop(target, None)
                    slot = self._slots.get(target)
                    if slot is not None:
                        slot.cancel_requested = True
                return False
        return True

    def has_active_execution(self, agent_id: str) -> bool:
        slot = self._slots.get(agent_id)
        return slot is not None and not slot.terminal.is_set()

    def active_execution(self, agent_id: str) -> ExecutionSlot | None:
        slot = self._slots.get(agent_id)
        return slot if slot is not None and not slot.terminal.is_set() else None

    def release_execution(self, agent_id: str, *, command_id: str | None = None, session_id: str | None = None) -> bool:
        slot = self._slots.get(agent_id)
        if slot is None:
            return False
        if command_id is not None and slot.command_id != command_id:
            return False
        if session_id is not None and slot.session_id != session_id:
            return False
        slot.terminal.set()
        self._slots.pop(agent_id, None)
        return True

    async def wait_for_execution_terminal(self, agent_id: str, timeout_seconds: float = 0.0) -> bool:
        slot = self.active_execution(agent_id)
        if slot is None:
            return True
        try:
            await asyncio.wait_for(slot.terminal.wait(), timeout=max(0.0, timeout_seconds))
        except TimeoutError:
            return False
        return True

    async def shutdown(self, timeout_seconds: float = 10.0) -> None:
        """Cancel active work and wait a bounded period for cooperative completion."""
        bounded_timeout = max(0.0, timeout_seconds)
        deadline = time.monotonic() + bounded_timeout
        cooperative_deadline = deadline - min(1.0, bounded_timeout * 0.2)
        sessions = list(self._sessions.values())
        slots = list(self._slots.items())

        for _, slot in slots:
            slot.cancel_requested = True

        async def wait_bounded(tasks: list[asyncio.Task[Any]], until: float) -> None:
            if not tasks:
                return
            remaining = max(0.0, until - time.monotonic())
            _, pending = await asyncio.wait(tasks, timeout=remaining)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        cancel_tasks = [
            asyncio.create_task(
                self.cancel_active_command(agent_id, session_id=slot.session_id)
            )
            for agent_id, slot in slots
            if self.is_current_session(agent_id, session_id=slot.session_id)
        ]
        await wait_bounded(cancel_tasks, cooperative_deadline)

        terminal_tasks = [asyncio.create_task(slot.terminal.wait()) for _, slot in slots if not slot.terminal.is_set()]
        await wait_bounded(terminal_tasks, cooperative_deadline)

        close_tasks = [asyncio.create_task(session.websocket.close(code=1001)) for session in sessions]
        await wait_bounded(close_tasks, deadline)

        # The timeout is a hard shutdown boundary. Releasing any remaining slots
        # prevents stale in-memory ownership if the app object is reused in tests.
        for agent_id, slot in slots:
            self.release_execution(agent_id, command_id=slot.command_id, session_id=slot.session_id)
        self._sessions.clear()
