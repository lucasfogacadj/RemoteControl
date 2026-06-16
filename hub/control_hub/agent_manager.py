from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class AgentManager:
    def __init__(self) -> None:
        self._agent_id: str | None = None
        self._websocket: WebSocket | None = None
        self._send_lock = asyncio.Lock()

    async def connect(self, agent_id: str, websocket: WebSocket) -> None:
        self._agent_id = agent_id
        self._websocket = websocket

    async def disconnect(self, agent_id: str) -> None:
        if self._agent_id == agent_id:
            self._agent_id = None
            self._websocket = None

    def is_connected(self) -> bool:
        return self._websocket is not None

    def snapshot(self) -> dict[str, Any]:
        return {"connected": self.is_connected(), "agent_id": self._agent_id}

    async def send_command(self, command: dict[str, Any]) -> bool:
        async with self._send_lock:
            websocket = self._websocket
            if websocket is None:
                return False
            try:
                await websocket.send_json({"type": "command", "command": command})
            except Exception:
                if self._websocket is websocket:
                    self._websocket = None
                    self._agent_id = None
                return False
            return True
