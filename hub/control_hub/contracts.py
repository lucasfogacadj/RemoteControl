from __future__ import annotations

import re
from typing import Any


LEGACY_AGENT_ID = "windows-desktop-01"
PROTOCOL_VERSION = "2"
AGENT_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
KNOWN_RESULT_STATUSES = {"success", "failure", "cancelled"}


class ProtocolError(ValueError):
    pass


def validate_agent_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ProtocolError("CONTROL_AGENT_ID deve ser texto.")
    agent_id = value.strip().lower()
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise ProtocolError(
            "CONTROL_AGENT_ID deve ter 1-64 caracteres minusculos e usar apenas letras, numeros, '.', '_' ou '-'."
        )
    return agent_id


def validate_hello(message: Any, query_agent_id: str | None = None) -> dict[str, Any]:
    """Validate the v2 hello while allowing the legacy query-only identity path."""

    if not isinstance(message, dict):
        raise ProtocolError("Hello deve ser um objeto.")
    agent_id = validate_agent_id(message.get("agent_id") or query_agent_id)
    if message.get("type") not in {None, "hello"}:
        raise ProtocolError("Mensagem inicial deve ser hello.")
    name = message.get("name", agent_id)
    version = message.get("version", "legacy")
    protocol = str(message.get("protocol", "1"))
    dry_run = message.get("dry_run", None)
    execution_idle = message.get("execution_idle", True)
    capabilities = message.get("capabilities", [])
    if not isinstance(name, str) or len(name.strip()) > 120:
        raise ProtocolError("Nome do agente invalido.")
    if not isinstance(version, str) or len(version.strip()) > 80:
        raise ProtocolError("Versao do agente invalida.")
    if dry_run is not None and not isinstance(dry_run, bool):
        raise ProtocolError("dry_run deve ser booleano.")
    if not isinstance(execution_idle, bool):
        raise ProtocolError("execution_idle deve ser booleano.")
    if not isinstance(capabilities, list) or not all(isinstance(item, str) and len(item) <= 80 for item in capabilities):
        raise ProtocolError("capabilities deve ser uma lista de textos curtos.")
    return {
        "agent_id": agent_id,
        "name": name.strip() or agent_id,
        "version": version.strip() or "legacy",
        "protocol": protocol,
        "dry_run": dry_run,
        "execution_idle": execution_idle,
        "capabilities": capabilities,
    }
