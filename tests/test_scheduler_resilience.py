import asyncio
import time

from hub.control_hub.agent_manager import AgentManager
from hub.control_hub.scheduler import RoutineScheduler


class FailingWebSocket:
    async def send_json(self, _payload):
        raise RuntimeError("socket closed")


class CloseableWebSocket:
    def __init__(self):
        self.close_code = None

    async def send_json(self, _payload):
        return None

    async def close(self, code=1000):
        self.close_code = code


def test_agent_manager_send_command_clears_stale_websocket():
    manager = AgentManager()
    asyncio.run(manager.connect("agent-1", FailingWebSocket()))

    sent = asyncio.run(manager.send_command({"type": "vscode_type_random_text"}))

    assert sent is False
    assert manager.snapshot() == {"connected": False, "agent_id": None}


def test_agent_manager_disconnect_ignores_replaced_websocket():
    manager = AgentManager()
    first = CloseableWebSocket()
    second = CloseableWebSocket()

    asyncio.run(manager.connect("agent-1", first))
    asyncio.run(manager.connect("agent-1", second))
    disconnected_old = asyncio.run(manager.disconnect("agent-1", first))

    assert disconnected_old is False
    assert manager.snapshot() == {"connected": True, "agent_id": "agent-1"}

    disconnected_current = asyncio.run(manager.disconnect("agent-1", second))

    assert disconnected_current is True
    assert manager.snapshot() == {"connected": False, "agent_id": None}


def test_agent_manager_disconnects_stale_heartbeat():
    manager = AgentManager(heartbeat_timeout_seconds=0.1)
    websocket = CloseableWebSocket()
    asyncio.run(manager.connect("agent-1", websocket))
    manager._last_seen_at = time.monotonic() - 1

    stale_agent_id = asyncio.run(manager.disconnect_if_stale())

    assert stale_agent_id == "agent-1"
    assert websocket.close_code == 4000
    assert manager.snapshot() == {"connected": False, "agent_id": None}


class RecordingStore:
    def __init__(self):
        self.events = []

    def record_event(self, kind, status, message, routine=None):
        self.events.append({"kind": kind, "status": status, "message": message, "routine": routine})


class RecoveringScheduler(RoutineScheduler):
    def __init__(self, store):
        super().__init__(store, AgentManager(), tick_seconds=0)
        self.calls = 0
        self._next_run_at = 0

    async def _tick(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        self.stop()


def test_scheduler_run_records_error_and_keeps_loop_alive():
    store = RecordingStore()
    scheduler = RecoveringScheduler(store)

    asyncio.run(asyncio.wait_for(scheduler.run(), timeout=1))

    assert scheduler.calls == 2
    assert store.events == [
        {
            "kind": "scheduler",
            "status": "error",
            "message": "Scheduler recuperou apos erro: boom",
            "routine": None,
        }
    ]


def test_scheduler_snapshot_reports_next_run_delay():
    store = RecordingStore()
    scheduler = RoutineScheduler(store, AgentManager())
    scheduler._next_run_at = time.monotonic() + 3

    snapshot = scheduler.snapshot()

    assert snapshot["running"] is True
    assert 0 < snapshot["next_run_in_seconds"] <= 3
