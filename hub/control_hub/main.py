from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from .agent_manager import AgentManager
from .config import load_config
from .contracts import KNOWN_RESULT_STATUSES, LEGACY_AGENT_ID, ProtocolError, validate_agent_id, validate_hello
from .domain import SettingsError, validate_settings
from .observability import setup_sentry
from .scheduler import RoutineScheduler
from .store import RevisionConflict, Store


config = load_config()
setup_sentry(config)
store = Store(config.database_path)
agent_manager = AgentManager(config.agent_heartbeat_timeout_seconds)
scheduler = RoutineScheduler(store, agent_manager, config.scheduler_tick_seconds, config.command_timeout_seconds)
scheduler_task: asyncio.Task[Any] | None = None
agent_watchdog_task: asyncio.Task[Any] | None = None
retention_task: asyncio.Task[Any] | None = None
static_dir = Path(__file__).parent / "static"


async def agent_watchdog_loop() -> None:
    interval = max(1.0, min(config.agent_heartbeat_timeout_seconds / 3, 10.0))
    while True:
        await asyncio.sleep(interval)
        stale_agents = await agent_manager.disconnect_stale()
        for agent_id in stale_agents:
            store.record_transition(
                agent_id,
                "connection",
                "offline",
                f"Agente sem heartbeat ha mais de {config.agent_heartbeat_timeout_seconds:g}s: {agent_id}",
                kind="agent",
            )
            store.set_agent_offline(agent_id, "heartbeat timeout")
            await scheduler.cancel_agent(agent_id, "Agente perdeu heartbeat durante uma rotina.")


async def retention_loop() -> None:
    # Bounded retention protects SQLite from large delete transactions. Run once at
    # startup and then periodically; it never touches active commands.
    while True:
        store.cleanup_terminal()
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler_task, agent_watchdog_task, retention_task
    store.init()
    store.mark_all_agents_offline("hub startup")
    scheduler_task = asyncio.create_task(scheduler.run())
    agent_watchdog_task = asyncio.create_task(agent_watchdog_loop())
    retention_task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        scheduler.stop()
        await scheduler.cancel_all("Hub em shutdown; comando cancelado cooperativamente.")
        await agent_manager.shutdown(config.shutdown_timeout_seconds)
        tasks = [task for task in (scheduler_task, agent_watchdog_task, retention_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        store.mark_all_agents_offline("hub shutdown")
        store.close()


app = FastAPI(title="Windows Activity Control", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _csp_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
    }


def _strict_enabled(payload: dict[str, Any]) -> bool:
    if set(payload) != {"enabled"} or not isinstance(payload.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="Campo 'enabled' booleano e obrigatorio.")
    return payload["enabled"]


def _agent_config_or_404(agent_id: str) -> dict[str, Any]:
    config_row = store.get_agent_config(agent_id)
    if config_row is None:
        raise HTTPException(status_code=404, detail="Agente nao encontrado.")
    return config_row


def _agent_state_payload(agent_id: str, *, events_limit: int = 50, commands_limit: int = 20) -> dict[str, Any]:
    snapshot = store.get_agent_snapshot(agent_id, events_limit=events_limit, commands_limit=commands_limit)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agente nao encontrado.")
    connection = agent_manager.snapshot(agent_id)
    snapshot["agent"]["online"] = connection["connected"]
    snapshot["agent"]["session_id"] = connection.get("session_id")
    snapshot["connection"] = connection
    snapshot["scheduler"] = scheduler.snapshot()["agents"].get(agent_id, {})
    return snapshot


def _etag(revision: int) -> str:
    return f'"{revision}"'


def _parse_expected_revision(if_match: str | None, payload: dict[str, Any]) -> int:
    candidate = if_match
    if candidate is None and "revision" in payload:
        candidate = str(payload.pop("revision"))
    if candidate is None:
        raise HTTPException(status_code=428, detail="If-Match com a revisao atual e obrigatorio.")
    normalized = candidate.strip().strip('"')
    try:
        revision = int(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="If-Match deve conter uma revisao inteira.") from exc
    if revision < 1:
        raise HTTPException(status_code=422, detail="If-Match deve conter uma revisao valida.")
    return revision


async def _cancel_agent(agent_id: str, message: str) -> int:
    return await scheduler.cancel_agent(agent_id, message)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html", headers=_csp_headers())


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health() -> dict[str, str]:
    # Compatibility contract intentionally remains minimal.
    return {"status": "ok"}


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    database = store.readiness()
    scheduler_running = scheduler_task is not None and not scheduler_task.done()
    watchdog_running = agent_watchdog_task is not None and not agent_watchdog_task.done()
    ready = bool(database["sqlite"] and database["migration"] and scheduler_running and watchdog_running)
    payload = {
        "status": "ok" if ready else "not_ready",
        "sqlite": database,
        "scheduler": scheduler_running,
        "watchdog": watchdog_running,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.get("/api/fleet/state")
def get_fleet_state() -> dict[str, Any]:
    fleet = store.get_fleet_state()
    scheduler_state = scheduler.snapshot()
    agents = store.list_agents()
    for agent in agents:
        connection = agent_manager.snapshot(agent["agent_id"])
        agent["online"] = connection["connected"]
        agent["connection"] = connection
        agent["schedule"] = scheduler_state["agents"].get(agent["agent_id"], {})
    return {
        "fleet": fleet,
        "agents": agents,
        "scheduler": {**scheduler_state, "task_running": scheduler_task is not None and not scheduler_task.done()},
        "watchdog": {"task_running": agent_watchdog_task is not None and not agent_watchdog_task.done()},
    }


@app.get("/api/agents/{agent_id}/state")
def get_agent_state(agent_id: str) -> dict[str, Any]:
    try:
        normalized = validate_agent_id(agent_id)
    except ProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _agent_state_payload(normalized)


@app.put("/api/agents/{agent_id}/settings")
async def put_agent_settings(
    response: Response,
    agent_id: str,
    payload: dict[str, Any] = Body(...),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    try:
        normalized = validate_agent_id(agent_id)
        expected_revision = _parse_expected_revision(if_match, payload)
        _agent_config_or_404(normalized)
        saved = store.save_agent_settings(normalized, payload, expected_revision=expected_revision, preserve_enabled=True)
    except ProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RevisionConflict as exc:
        raise HTTPException(
            status_code=412,
            detail={"message": str(exc), "current_revision": exc.current_revision},
        ) from exc
    scheduler.reset_agent(normalized)
    store.record_event("settings", "ok", "Configuracao atualizada.", agent_id=normalized)
    response.headers["ETag"] = _etag(saved["revision"])
    return saved


@app.post("/api/agents/{agent_id}/toggle")
async def toggle_agent(agent_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        normalized = validate_agent_id(agent_id)
        enabled = _strict_enabled(payload)
        _agent_config_or_404(normalized)
        saved = store.set_agent_enabled(normalized, enabled)
    except ProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    status = "ativado" if enabled else "desativado"
    store.record_event("settings", "ok", f"PC {status} individualmente.", agent_id=normalized)
    if not enabled:
        await _cancel_agent(normalized, "PC desativado individualmente.")
    return saved


@app.post("/api/agents/{agent_id}/cancel")
async def cancel_agent(agent_id: str) -> dict[str, Any]:
    try:
        normalized = validate_agent_id(agent_id)
        _agent_config_or_404(normalized)
    except ProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cancelled = await _cancel_agent(normalized, "Cancelamento solicitado pelo operador.")
    return {"agent_id": normalized, "cancelled": cancelled}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    """Temporary explicit alias for the migrated legacy PC, never last heartbeat."""
    state = _agent_state_payload(LEGACY_AGENT_ID)
    return {
        "settings": state["settings"],
        "agent": state["agent"],
        "connection": state["connection"],
        "scheduler": state["scheduler"],
        "events": state["events"],
        "commands": state["commands"],
    }


@app.get("/api/settings")
def get_legacy_settings(response: Response) -> dict[str, Any]:
    saved = _agent_config_or_404(LEGACY_AGENT_ID)
    response.headers["ETag"] = _etag(saved["revision"])
    return saved


@app.put("/api/settings")
async def put_legacy_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Compatibility adapter for old clients; maps strictly to windows-desktop-01."""
    try:
        saved = store.save_agent_settings(LEGACY_AGENT_ID, payload, preserve_enabled=False)
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reset_agent(LEGACY_AGENT_ID)
    store.record_event("settings", "ok", "Configuracao legado atualizada.", agent_id=LEGACY_AGENT_ID)
    if not saved["enabled"]:
        await _cancel_agent(LEGACY_AGENT_ID, "PC legado desativado por configuracao.")
    return saved["settings"]


@app.post("/api/toggle")
async def toggle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    enabled = _strict_enabled(payload)
    fleet = store.set_fleet_enabled(enabled)
    store.record_event("fleet", "ok", f"Frota {'ativada' if enabled else 'pausada'}.")
    if not enabled:
        await scheduler.cancel_all("Frota pausada pelo master switch.")
    return fleet


@app.get("/api/events")
def events(
    agent_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    if agent_id is not None:
        try:
            agent_id = validate_agent_id(agent_id)
        except ProtocolError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return store.list_events_page(limit=limit, agent_id=agent_id, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/commands")
def commands(
    agent_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    if agent_id is not None:
        try:
            agent_id = validate_agent_id(agent_id)
        except ProtocolError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return store.list_commands_page(limit=limit, agent_id=agent_id, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _process_agent_message(
    agent_id: str,
    session_id: str,
    websocket: WebSocket,
    message: dict[str, Any],
) -> None:
    message_type = message.get("type")
    if not agent_manager.is_current_session(agent_id, websocket=websocket, session_id=session_id):
        command_id = str(message.get("command_id", "")) or None
        routine = str(message.get("routine", "")) or None
        status = "late_result" if message_type == "result" else "rejected"
        store.record_event(
            "command" if message_type == "result" else "agent",
            status,
            "Mensagem de uma sessao substituida ignorada.",
            routine=routine,
            agent_id=agent_id,
            command_id=command_id,
        )
        return
    if message_type == "hello":
        # A repeat hello is accepted only when it proves the same identity.
        hello = validate_hello(message, agent_id)
        if hello["agent_id"] != agent_id:
            raise ProtocolError("hello nao pode mudar o agent_id da sessao.")
        store.touch_agent(agent_id, "hello atualizado", session_id=session_id, metadata=hello)
        return
    if message_type == "heartbeat":
        supplied_agent = message.get("agent_id", agent_id)
        supplied_session = message.get("session_id", session_id)
        if supplied_agent != agent_id or supplied_session != session_id:
            store.record_event("agent", "rejected", "Heartbeat de outra sessao ignorado.", agent_id=agent_id)
            return
        if await agent_manager.record_heartbeat(agent_id, websocket, session_id):
            store.touch_agent(agent_id, str(message.get("message", "heartbeat")), session_id=session_id)
        return
    if message_type == "result":
        command_id = str(message.get("command_id", ""))
        status = message.get("status")
        result_message = str(message.get("message", ""))
        routine = str(message.get("routine", ""))
        supplied_agent = message.get("agent_id", agent_id)
        supplied_session = message.get("session_id", session_id)
        if not command_id or supplied_agent != agent_id or supplied_session != session_id or status not in KNOWN_RESULT_STATUSES:
            store.record_event(
                "command", "late_result", "Resultado invalido ou sem correlacao rejeitado.", routine=routine or None, agent_id=agent_id, command_id=command_id or None
            )
            return
        accepted = store.mark_command_result(
            command_id, status, result_message, agent_id=agent_id, session_id=session_id
        )
        if accepted:
            store.record_event(
                "command", status, result_message, routine=routine or None, agent_id=agent_id, command_id=command_id
            )
            agent_manager.release_execution(agent_id, command_id=command_id, session_id=session_id)
        else:
            store.record_event(
                "command", "late_result", result_message or "Resultado tardio ignorado.", routine=routine or None, agent_id=agent_id, command_id=command_id
            )
            # A terminal update may have won the race (cancel/timeout) before the
            # cooperative worker could reply. Its reply still proves the slot ended.
            agent_manager.release_execution(agent_id, command_id=command_id, session_id=session_id)
        return
    store.record_event("agent", "ignored", f"Mensagem desconhecida: {message_type}", agent_id=agent_id)


async def _receive_agent_json(websocket: WebSocket) -> dict[str, Any]:
    """Read a message unless a watchdog or replacement already closed the socket."""
    # `AgentManager.disconnect_stale()` and reconnect handling can close a socket
    # from another task while this handler is waiting for the next message. Starlette
    # then raises RuntimeError before reading; model that expected close as a normal
    # WebSocket disconnect instead.
    if websocket.application_state is not WebSocketState.CONNECTED:
        raise WebSocketDisconnect(code=1000)
    return await websocket.receive_json()


@app.websocket("/ws/agent")
async def agent_socket(
    websocket: WebSocket,
    token: str = Query(default=""),
    agent_id: str = Query(default=""),
    authorization: str | None = Header(default=None),
) -> None:
    if authorization is None:
        supplied_token = token
    else:
        scheme, separator, credentials = authorization.partition(" ")
        supplied_token = credentials.strip() if separator and scheme.lower() == "bearer" else ""
    if supplied_token != config.pairing_token:
        store.record_event("agent", "rejected", "Agente rejeitado por token invalido.")
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session_id: str | None = None
    normalized_agent_id: str | None = None
    try:
        first_message = await _receive_agent_json(websocket)
        if first_message.get("type") == "hello":
            hello = validate_hello(first_message, agent_id or None)
        else:
            # Legacy clients provide identity in the query string and start with a heartbeat.
            normalized = validate_agent_id(agent_id)
            hello = {
                "agent_id": normalized,
                "name": normalized,
                "version": "legacy",
                "protocol": "1",
                "dry_run": None,
                "capabilities": [],
            }
        normalized_agent_id = hello["agent_id"]
        onboarded = store.ensure_agent(normalized_agent_id, enabled=False)
        session = await agent_manager.connect(normalized_agent_id, websocket, hello)
        session_id = session.session_id
        store.touch_agent(normalized_agent_id, "connected", session_id=session_id, metadata=hello)
        store.record_transition(normalized_agent_id, "connection", "ok", f"Agente conectado: {normalized_agent_id}", kind="agent")
        if onboarded:
            store.record_event("agent", "onboarded", "Novo PC cadastrado desativado.", agent_id=normalized_agent_id)
        await websocket.send_json({"type": "hello_ack", "session_id": session_id, "protocol": "2"})
        if first_message.get("type") != "hello":
            await _process_agent_message(normalized_agent_id, session_id, websocket, first_message)
        while True:
            message = await _receive_agent_json(websocket)
            await _process_agent_message(normalized_agent_id, session_id, websocket, message)
    except ProtocolError as exc:
        if normalized_agent_id:
            store.record_event("agent", "rejected", str(exc), agent_id=normalized_agent_id)
        else:
            store.record_event("agent", "rejected", str(exc))
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if normalized_agent_id and session_id:
            disconnected_current = await agent_manager.disconnect(normalized_agent_id, websocket, session_id)
            if disconnected_current:
                store.record_transition(
                    normalized_agent_id, "connection", "offline", f"Agente desconectado: {normalized_agent_id}", kind="agent"
                )
                store.set_agent_offline(normalized_agent_id, "disconnected")
                await scheduler.cancel_agent(normalized_agent_id, "Agente desconectado durante uma rotina.")
