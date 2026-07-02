from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import WebSocket


class AgentManager:
    def __init__(self, heartbeat_timeout_seconds: float = 45.0) -> None:
        self._agent_id: str | None = None
        self._websocket: WebSocket | None = None
        self._last_seen_at: float | None = None
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._send_lock = asyncio.Lock()

    async def connect(self, agent_id: str, websocket: WebSocket) -> WebSocket | None:
        previous = self._websocket
        self._agent_id = agent_id
        self._websocket = websocket
        self._last_seen_at = time.monotonic()
        return previous if previous is not websocket else None

    async def disconnect(self, agent_id: str, websocket: WebSocket | None = None) -> bool:
        if self._agent_id == agent_id and (websocket is None or self._websocket is websocket):
            self._agent_id = None
            self._websocket = None
            self._last_seen_at = None
            return True
        return False

    async def record_heartbeat(self, agent_id: str, websocket: WebSocket | None = None) -> None:
        if self._agent_id == agent_id and (websocket is None or self._websocket is websocket):
            self._last_seen_at = time.monotonic()

    def _is_stale(self, now: float | None = None) -> bool:
        if self._websocket is None or self._last_seen_at is None:
            return False
        now = time.monotonic() if now is None else now
        return now - self._last_seen_at > self.heartbeat_timeout_seconds

    async def disconnect_if_stale(self) -> str | None:
        if not self._is_stale():
            return None

        agent_id = self._agent_id
        websocket = self._websocket
        self._agent_id = None
        self._websocket = None
        self._last_seen_at = None

        if websocket is not None:
            try:
                await websocket.close(code=4000)
            except Exception:
                pass
        return agent_id

    def is_connected(self) -> bool:
        return self._websocket is not None and not self._is_stale()

    def snapshot(self) -> dict[str, Any]:
        return {"connected": self.is_connected(), "agent_id": self._agent_id}

    async def send_control(self, action: str) -> bool:
        return await self._send_json({"type": "control", "action": action})

    async def cancel_active_command(self) -> bool:
        return await self.send_control("cancel_active_command")

    async def send_command(self, command: dict[str, Any]) -> bool:
        return await self._send_json({"type": "command", "command": command})

    async def _send_json(self, payload: dict[str, Any]) -> bool:
        async with self._send_lock:
            websocket = self._websocket
            if websocket is None:
                return False
            try:
                await websocket.send_json(payload)
            except Exception:
                if self._websocket is websocket:
                    self._websocket = None
                    self._agent_id = None
                    self._last_seen_at = None
                return False
            return True
