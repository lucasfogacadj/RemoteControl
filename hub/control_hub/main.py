from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent_manager import AgentManager
from .config import load_config
from .domain import SettingsError, validate_settings
from .scheduler import RoutineScheduler
from .store import Store


config = load_config()
store = Store(config.database_path)
agent_manager = AgentManager()
scheduler = RoutineScheduler(store, agent_manager, config.scheduler_tick_seconds)
scheduler_task: asyncio.Task[Any] | None = None
static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler_task
    store.init()
    scheduler_task = asyncio.create_task(scheduler.run())
    try:
        yield
    finally:
        scheduler.stop()
        if scheduler_task:
            scheduler_task.cancel()


app = FastAPI(title="Windows Activity Control", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return {
        "settings": store.get_settings(),
        "agent": store.get_agent_state(),
        "connection": agent_manager.snapshot(),
        "events": store.list_events(),
        "commands": store.list_commands(),
    }


@app.put("/api/settings")
def put_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        settings = validate_settings(payload)
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = store.save_settings(settings)
    store.record_event("settings", "ok", "Configuracao atualizada.")
    if not saved["enabled"]:
        cancelled = store.cancel_pending_commands()
        if cancelled:
            store.record_event("command", "cancelled", f"{cancelled} comando(s) pendente(s) cancelado(s).")
    return saved


@app.post("/api/toggle")
def toggle(payload: dict[str, bool] = Body(...)) -> dict[str, Any]:
    if "enabled" not in payload:
        raise HTTPException(status_code=422, detail="Campo 'enabled' e obrigatorio.")
    settings = store.get_settings()
    settings["enabled"] = bool(payload["enabled"])
    try:
        saved = store.save_settings(settings)
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    status = "ativada" if saved["enabled"] else "desativada"
    store.record_event("settings", "ok", f"Automacao {status}.")
    if not saved["enabled"]:
        cancelled = store.cancel_pending_commands()
        if cancelled:
            store.record_event("command", "cancelled", f"{cancelled} comando(s) pendente(s) cancelado(s).")
    return saved


@app.get("/api/events")
def events(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return store.list_events(limit=limit)


@app.websocket("/ws/agent")
async def agent_socket(
    websocket: WebSocket,
    token: str = Query(default=""),
    agent_id: str = Query(default="windows-agent"),
) -> None:
    if token != config.pairing_token:
        store.record_event("agent", "rejected", "Agente rejeitado por token invalido.")
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await agent_manager.connect(agent_id, websocket)
    store.touch_agent(agent_id, "connected")
    store.record_event("agent", "ok", f"Agente conectado: {agent_id}")
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "heartbeat":
                store.touch_agent(agent_id, message.get("message", "heartbeat"))
            elif message_type == "result":
                command_id = str(message.get("command_id", ""))
                status = str(message.get("status", "unknown"))
                routine = str(message.get("routine", ""))
                result_message = str(message.get("message", ""))
                if command_id:
                    store.mark_command_result(command_id, status, result_message)
                store.record_event("command", status, result_message, routine=routine)
            else:
                store.record_event("agent", "ignored", f"Mensagem desconhecida: {message_type}")
    except WebSocketDisconnect:
        store.record_event("agent", "offline", f"Agente desconectado: {agent_id}")
    finally:
        await agent_manager.disconnect(agent_id)
        store.set_agent_offline(agent_id, "disconnected")
