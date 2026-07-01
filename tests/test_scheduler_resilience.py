import asyncio
from datetime import UTC, datetime, timedelta
import time

from hub.control_hub.agent_manager import AgentManager
from hub.control_hub.domain import default_settings
from hub.control_hub.scheduler import RoutineScheduler
from hub.control_hub.store import Store


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


def enabled_vscode_settings():
    settings = default_settings()
    settings["enabled"] = True
    settings["min_interval_seconds"] = 5
    settings["max_interval_seconds"] = 5
    settings["vscode_target_file"] = r"C:\Temp\control-target.go"
    for routine in settings["routines"]:
        routine["enabled"] = routine["id"] == "vscode_type_random_text"
        routine["percentage"] = 100 if routine["id"] == "vscode_type_random_text" else 0
    return settings


class RecordingAgentManager:
    def __init__(self, store=None, result_status=None):
        self.store = store
        self.result_status = result_status
        self.sent = []

    def is_connected(self):
        return True

    async def send_command(self, command):
        self.sent.append(command.copy())
        if self.store and self.result_status:
            self.store.mark_command_result(command["id"], self.result_status, "done")
        return True


def initialized_store(tmp_path):
    store = Store(str(tmp_path / "control.db"))
    store.init()
    store.save_settings(enabled_vscode_settings())
    return store


def run_due_tick(scheduler):
    scheduler._next_run_at = 0
    asyncio.run(scheduler._tick())


def test_scheduler_waits_for_active_command_before_dispatch(tmp_path):
    store = initialized_store(tmp_path)
    store.create_command("active", {"id": "active", "type": "vscode_type_random_text", "params": {}}, status="dispatched")
    manager = RecordingAgentManager()
    scheduler = RoutineScheduler(store, manager, tick_seconds=0, command_timeout_seconds=120)

    run_due_tick(scheduler)

    assert manager.sent == []
    assert store.get_active_command()["id"] == "active"


def test_scheduler_times_out_stale_command_before_dispatching_next(tmp_path):
    store = initialized_store(tmp_path)
    store.create_command("old", {"id": "old", "type": "vscode_type_random_text", "params": {}}, status="dispatched")
    stale_time = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    with store._lock:
        store._conn.execute("UPDATE commands SET created_at = ?, updated_at = ? WHERE id = ?", (stale_time, stale_time, "old"))
        store._conn.commit()
    manager = RecordingAgentManager()
    scheduler = RoutineScheduler(store, manager, tick_seconds=0, command_timeout_seconds=5)

    run_due_tick(scheduler)

    commands = {command["id"]: command for command in store.list_commands()}
    assert commands["old"]["status"] == "timeout"
    assert commands["old"]["result_message"] == "Comando sem resposta do agente por mais de 5s."
    assert len(manager.sent) == 1
    assert any(event["status"] == "timeout" and event["routine"] == "vscode_type_random_text" for event in store.list_events())


def test_scheduler_preserves_fast_result_received_during_send(tmp_path):
    store = initialized_store(tmp_path)
    manager = RecordingAgentManager(store, result_status="success")
    scheduler = RoutineScheduler(store, manager, tick_seconds=0, command_timeout_seconds=120)

    run_due_tick(scheduler)

    commands = store.list_commands()
    assert len(manager.sent) == 1
    assert commands[0]["status"] == "success"
    assert commands[0]["result_message"] == "done"
