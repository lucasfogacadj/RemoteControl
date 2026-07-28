import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import time
import threading
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

import hub.control_hub.main as main
from hub.control_hub.agent_manager import AgentManager
from hub.control_hub.domain import SettingsError, default_settings, validate_settings
from hub.control_hub.scheduler import RoutineScheduler
from hub.control_hub.store import ActiveCommandConflict, LEGACY_AGENT_ID, Store
from hub.control_hub.rhythm import RhythmEngine
from windows_agent.agent import hello_message, result as agent_result


class RecordingWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = None

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000):
        self.closed = code


class ClosedApplicationWebSocket:
    application_state = WebSocketState.DISCONNECTED

    async def receive_json(self):  # pragma: no cover - the state guard must prevent this call.
        raise AssertionError("receive_json nao deve ser chamado em socket fechado")


@contextmanager
def temporary_main_app(tmp_path):
    previous = main.store, main.agent_manager, main.scheduler
    main.store = Store(str(tmp_path / "control.db"))
    main.agent_manager = AgentManager()
    main.scheduler = RoutineScheduler(main.store, main.agent_manager, tick_seconds=60)
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.store, main.agent_manager, main.scheduler = previous


def hello(agent_id):
    return {
        "type": "hello",
        "agent_id": agent_id,
        "name": agent_id,
        "version": "test-2",
        "protocol": "2",
        "dry_run": True,
        "capabilities": ["open_gmail"],
    }


def test_agent_socket_treats_a_watchdog_closed_socket_as_a_normal_disconnect():
    with pytest.raises(WebSocketDisconnect):
        asyncio.run(main._receive_agent_json(ClosedApplicationWebSocket()))


def test_migration_backs_up_singleton_database_and_cancels_legacy_active_command(tmp_path):
    path = tmp_path / "legacy.db"
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE agent_state (agent_id TEXT PRIMARY KEY, online INTEGER NOT NULL, last_heartbeat TEXT, last_message TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, routine TEXT, message TEXT NOT NULL);
            CREATE TABLE commands (id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_message TEXT);
            """
        )
        settings = default_settings()
        settings["enabled"] = True
        conn.execute("INSERT INTO settings VALUES (1, ?, ?)", (json.dumps(settings), now))
        conn.execute(
            "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, NULL)",
            ("legacy-active", "open_gmail", "dispatched", json.dumps({"id": "legacy-active", "type": "open_gmail"}), now, now),
        )

    store = Store(str(path))
    store.init()
    try:
        assert Path(store.last_backup_path).exists()
        assert store.integrity_check() == "ok"
        assert store.get_fleet_state()["enabled"] is False
        assert store.get_agent_config(LEGACY_AGENT_ID)["enabled"] is True
        assert store.list_commands()[0]["status"] == "cancelled"
        assert store.list_commands()[0]["legacy_unassigned"] is True
    finally:
        store.close()


def test_strict_settings_rejects_boolean_coercion_duplicates_and_non_finite_values():
    settings = default_settings()
    settings["enabled"] = "false"
    with pytest.raises(SettingsError, match="booleano"):
        validate_settings(settings)

    settings = default_settings()
    settings["routines"].append(dict(settings["routines"][0]))
    with pytest.raises(SettingsError, match="duplicado"):
        validate_settings(settings)

    settings = default_settings()
    settings["typo_rate"] = float("inf")
    with pytest.raises(SettingsError, match="finito"):
        validate_settings(settings)

    settings = default_settings()
    settings["timezone"] = "Not/AZone"
    with pytest.raises(SettingsError, match="IANA"):
        validate_settings(settings)


def test_agent_manager_reconnect_and_execution_slots_are_scoped_per_agent():
    async def scenario():
        manager = AgentManager()
        first_a = RecordingWebSocket()
        b = RecordingWebSocket()
        second_a = RecordingWebSocket()
        session_a1 = await manager.connect("agent-a", first_a)
        session_b = await manager.connect("agent-b", b)
        session_a2 = await manager.connect("agent-a", second_a)

        assert first_a.closed == 4001
        assert manager.get_session("agent-b").session_id == session_b.session_id
        assert not await manager.record_heartbeat("agent-a", first_a, session_a1.session_id)
        assert await manager.send_command({"id": "a-1", "type": "open_gmail"}, agent_id="agent-a")
        assert manager.has_active_execution("agent-a")
        assert await manager.send_command({"id": "b-1", "type": "open_gmail"}, agent_id="agent-b")
        assert manager.has_active_execution("agent-b")
        assert not await manager.send_command({"id": "a-2", "type": "open_gmail"}, agent_id="agent-a")
        assert manager.release_execution("agent-a", command_id="a-1", session_id=session_a2.session_id)

    asyncio.run(scenario())


def test_agent_manager_keeps_ten_agents_and_their_commands_isolated():
    async def scenario():
        manager = AgentManager()
        sockets = {f"agent-{index}": RecordingWebSocket() for index in range(10)}
        for agent_id, socket in sockets.items():
            await manager.connect(agent_id, socket)
        assert len(manager.fleet_snapshot()) == 10
        for agent_id in sockets:
            assert await manager.send_command({"id": f"command-{agent_id}", "type": "open_gmail"}, agent_id=agent_id)
        assert all(manager.has_active_execution(agent_id) for agent_id in sockets)
        assert all(len(socket.sent) == 1 for socket in sockets.values())

    asyncio.run(scenario())


def test_agent_manager_shutdown_waits_for_cooperative_terminal_and_is_bounded():
    async def cooperative_scenario():
        manager = AgentManager()
        socket = RecordingWebSocket()
        session = await manager.connect("agent-a", socket)
        assert await manager.send_command({"id": "command-a", "type": "open_gmail"}, agent_id="agent-a")

        async def finish_worker():
            await asyncio.sleep(0.01)
            manager.release_execution("agent-a", command_id="command-a", session_id=session.session_id)

        worker = asyncio.create_task(finish_worker())
        await manager.shutdown(timeout_seconds=0.5)
        await worker
        assert not manager.has_active_execution("agent-a")
        assert manager.fleet_snapshot() == {}
        assert socket.closed == 1001
        assert any(item == {"type": "control", "action": "cancel_active_command"} for item in socket.sent)

    async def bounded_scenario():
        manager = AgentManager()
        socket = RecordingWebSocket()
        await manager.connect("agent-a", socket)
        assert await manager.send_command({"id": "command-a", "type": "open_gmail"}, agent_id="agent-a")
        started = time.monotonic()
        await manager.shutdown(timeout_seconds=0.05)
        assert time.monotonic() - started < 0.25
        assert not manager.has_active_execution("agent-a")
        assert manager.fleet_snapshot() == {}

    asyncio.run(cooperative_scenario())
    asyncio.run(bounded_scenario())


def test_agent_protocol_hello_and_result_keep_session_ownership():
    config = type("Config", (), {"agent_id": "agent-a", "agent_name": "Agent A", "dry_run": True})()
    hello_payload = hello_message(config)
    assert hello_payload["type"] == "hello"
    assert hello_payload["agent_id"] == "agent-a"
    assert hello_payload["execution_idle"] is True
    response = agent_result(
        {"id": "command-a", "type": "open_gmail", "agent_id": "agent-a", "session_id": "session-a"},
        "success",
        "done",
    )
    assert response["agent_id"] == "agent-a"
    assert response["session_id"] == "session-a"


def test_store_scopes_active_commands_results_cursors_and_retention(tmp_path):
    store = Store(str(tmp_path / "control.db"))
    store.init()
    try:
        store.ensure_agent("agent-a")
        store.ensure_agent("agent-b")
        store.create_command("a-1", {"id": "a-1", "type": "open_gmail"}, "dispatched", agent_id="agent-a", session_id="s-a")
        store.create_command("b-1", {"id": "b-1", "type": "open_gmail"}, "dispatched", agent_id="agent-b", session_id="s-b")
        with pytest.raises(ActiveCommandConflict):
            store.create_command("a-2", {"id": "a-2", "type": "open_gmail"}, "queued", agent_id="agent-a", session_id="s-a")
        assert not store.mark_command_result("a-1", "success", "forged", agent_id="agent-b", session_id="s-b")
        assert store.mark_command_result("a-1", "success", "done", agent_id="agent-a", session_id="s-a")
        store.record_event("command", "success", "a", agent_id="agent-a", command_id="a-1")
        store.record_event("command", "success", "b", agent_id="agent-b", command_id="b-1")
        page = store.list_events_page(agent_id="agent-a", limit=1)
        assert [event["agent_id"] for event in page["items"]] == ["agent-a"]
        old = (datetime.now(UTC) - timedelta(days=91)).isoformat()
        with store._lock:
            store._conn.execute("UPDATE commands SET updated_at = ? WHERE id = 'a-1'", (old,))
            store._conn.commit()
        result = store.cleanup_terminal(batch_size=10)
        assert result["commands"] == 1
        assert store.get_active_command("agent-b")["id"] == "b-1"
    finally:
        store.close()


def test_scheduler_times_out_on_every_tick_and_cancels_when_window_closes(tmp_path):
    store = Store(str(tmp_path / "control.db"))
    store.init()
    manager = AgentManager()
    scheduler = RoutineScheduler(store, manager, tick_seconds=60)
    try:
        store.ensure_agent("agent-a")
        settings = default_settings()
        settings["vscode_target_file"] = r"C:\Temp\target.txt"
        settings["work_start"] = "00:00"
        settings["work_end"] = "00:01"
        store.save_agent_settings("agent-a", settings, preserve_enabled=False)
        store.set_agent_enabled("agent-a", True)
        store.create_command("window-command", {"id": "window-command", "type": "open_gmail"}, "dispatched", agent_id="agent-a")
        store.ensure_agent("agent-b")
        store.create_command(
            "expired-command",
            {"id": "expired-command", "type": "open_gmail"},
            "dispatched",
            agent_id="agent-b",
            deadline_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
        scheduler._ensure_runtime("agent-b").next_run_at = time.monotonic() + 600
        asyncio.run(scheduler._tick())
        assert store.list_commands(agent_id="agent-a")[0]["status"] == "cancelled"
        assert store.list_commands(agent_id="agent-b")[0]["status"] == "timeout"
    finally:
        store.close()


def test_scheduler_uses_aware_timezones_without_profile_workday_override(tmp_path):
    store = Store(str(tmp_path / "control.db"))
    store.init()
    fixed_now = datetime(2026, 7, 12, 12, tzinfo=UTC)
    scheduler = RoutineScheduler(
        store,
        AgentManager(),
        tick_seconds=60,
        now_provider=lambda zone: fixed_now.astimezone(zone),
    )
    try:
        for timezone in ("UTC", "America/Sao_Paulo", "America/New_York"):
            now = datetime.now(ZoneInfo(timezone))
            settings = default_settings()
            settings["timezone"] = timezone
            settings["work_start"] = "00:00"
            settings["work_end"] = "23:59"
            settings["profile"] = "freelancer"
            assert scheduler._inside_work_window(settings)
            # An aware provider on a DST transition must still build a rhythm plan.
            engine = RhythmEngine(now_provider=lambda: datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo("America/New_York")))
            assert engine.evaluate(settings).energy >= 0
    finally:
        store.close()


def test_ten_agent_heartbeat_load_uses_one_sqlite_connection_without_lock_errors(tmp_path):
    store = Store(str(tmp_path / "control.db"))
    store.init()
    errors = []

    def heartbeat(agent_id):
        try:
            for index in range(20):
                store.touch_agent(agent_id, f"heartbeat-{index}")
                store.record_transition(agent_id, "availability", "ok", "online")
        except Exception as exc:  # pragma: no cover - assertion below is the intent
            errors.append(exc)

    try:
        threads = [threading.Thread(target=heartbeat, args=(f"agent-{index}",)) for index in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(store.list_agents()) == 11  # ten test agents plus migrated legacy agent
        assert len(store.list_events(agent_id="agent-0")) == 1  # transition was deduplicated
    finally:
        store.close()


def test_http_fleet_settings_etag_toggle_and_legacy_alias_are_isolated(tmp_path):
    with temporary_main_app(tmp_path) as client:
        with client.websocket_connect("/ws/agent?token=dev-change-me&agent_id=agent-a") as socket:
            socket.send_json(hello("agent-a"))
            socket.receive_json()
            fleet = client.get("/api/fleet/state").json()
            agent_a = next(agent for agent in fleet["agents"] if agent["agent_id"] == "agent-a")
            assert agent_a["enabled"] is False

            detail = client.get("/api/agents/agent-a/state").json()
            settings = detail["settings"]
            response = client.put("/api/agents/agent-a/settings", json=settings, headers={"If-Match": '"1"'})
            assert response.status_code == 200
            assert response.headers["etag"] == '"2"'
            assert client.put("/api/agents/agent-a/settings", json=settings, headers={"If-Match": '"1"'}).status_code == 412

            assert client.post("/api/agents/agent-a/toggle", json={"enabled": True}).json()["enabled"] is True
            assert client.post("/api/toggle", json={"enabled": False}).json()["enabled"] is False
            legacy = client.get("/api/state").json()
            assert legacy["agent"]["agent_id"] == LEGACY_AGENT_ID
            assert client.get("/api/agents/not valid/state").status_code == 422


def test_websocket_accepts_bearer_header_and_keeps_legacy_query_token(tmp_path):
    with temporary_main_app(tmp_path) as client:
        with client.websocket_connect(
            "/ws/agent?agent_id=agent-header",
            headers={"Authorization": "Bearer dev-change-me"},
        ) as socket:
            socket.send_json(hello("agent-header"))
            assert socket.receive_json()["type"] == "hello_ack"

        with client.websocket_connect("/ws/agent?token=dev-change-me&agent_id=agent-legacy") as socket:
            socket.send_json(hello("agent-legacy"))
            assert socket.receive_json()["type"] == "hello_ack"


def test_websocket_rejects_cross_agent_result_and_accepts_matching_result(tmp_path):
    with temporary_main_app(tmp_path) as client:
        with client.websocket_connect("/ws/agent?token=dev-change-me&agent_id=agent-a") as socket_a:
            socket_a.send_json(hello("agent-a"))
            session_a = socket_a.receive_json()["session_id"]
            with client.websocket_connect("/ws/agent?token=dev-change-me&agent_id=agent-b") as socket_b:
                socket_b.send_json(hello("agent-b"))
                session_b = socket_b.receive_json()["session_id"]
                main.store.create_command(
                    "owned-by-a",
                    {"id": "owned-by-a", "type": "open_gmail"},
                    "dispatched",
                    agent_id="agent-a",
                    session_id=session_a,
                )
                socket_b.send_json(
                    {"type": "result", "command_id": "owned-by-a", "agent_id": "agent-b", "session_id": session_b, "status": "success", "message": "forged"}
                )
                assert main.store.get_active_command("agent-a")["id"] == "owned-by-a"
                socket_a.send_json(
                    {"type": "result", "command_id": "owned-by-a", "agent_id": "agent-a", "session_id": session_a, "status": "success", "message": "done"}
                )
                for _ in range(20):
                    if main.store.list_commands(agent_id="agent-a")[0]["status"] == "success":
                        break
                    time.sleep(0.01)
                assert main.store.list_commands(agent_id="agent-a")[0]["status"] == "success"


def test_replaced_session_result_is_recorded_late_without_completing_command(tmp_path):
    async def scenario():
        previous = main.store, main.agent_manager, main.scheduler
        test_store = Store(str(tmp_path / "control.db"))
        test_store.init()
        manager = AgentManager()
        main.store = test_store
        main.agent_manager = manager
        main.scheduler = RoutineScheduler(test_store, manager, tick_seconds=60)
        try:
            test_store.ensure_agent("agent-a")
            first = RecordingWebSocket()
            first_session = await manager.connect("agent-a", first)
            assert await manager.send_command(
                {"id": "stale-command", "type": "open_gmail"},
                agent_id="agent-a",
                session_id=first_session.session_id,
            )
            test_store.create_command(
                "stale-command",
                {"id": "stale-command", "type": "open_gmail"},
                "dispatched",
                agent_id="agent-a",
                session_id=first_session.session_id,
            )

            second = RecordingWebSocket()
            current_session = await manager.connect("agent-a", second, {"execution_idle": False})
            await main._process_agent_message(
                "agent-a",
                first_session.session_id,
                first,
                {
                    "type": "result",
                    "command_id": "stale-command",
                    "agent_id": "agent-a",
                    "session_id": first_session.session_id,
                    "status": "success",
                    "message": "stale success",
                },
            )

            assert manager.get_session("agent-a").session_id == current_session.session_id
            assert test_store.list_commands(agent_id="agent-a")[0]["status"] == "dispatched"
            assert test_store.list_events(agent_id="agent-a")[0]["status"] == "late_result"
        finally:
            await manager.shutdown(timeout_seconds=0.01)
            test_store.close()
            main.store, main.agent_manager, main.scheduler = previous

    asyncio.run(scenario())


def test_console_uses_csp_and_safe_dynamic_rendering(tmp_path):
    index_html = (Path(__file__).parents[1] / "hub" / "control_hub" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (Path(__file__).parents[1] / "hub" / "control_hub" / "static" / "app.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in app_js
    assert "textContent" in app_js
    assert 'id="dirtySelectionDialog"' in index_html
    assert "Salvar e trocar" in index_html
    assert "Descartar" in index_html
    assert "Cancelar" in index_html
    assert "window.confirm" not in app_js
    assert "saveAndSwitchAgent" in app_js
    assert "discardAndSwitchAgent" in app_js
    assert "Há alterações não salvas" in app_js
    dockerfile = (Path(__file__).parents[1] / "hub" / "Dockerfile").read_text(encoding="utf-8")
    assert "--workers 1" in dockerfile
    assert "--no-access-log" in dockerfile
    assert "--log-level warning" in dockerfile
    with temporary_main_app(tmp_path) as client:
        response = client.get("/")
        assert "Content-Security-Policy" in response.headers
        assert "script-src 'self'" in response.headers["Content-Security-Policy"]
