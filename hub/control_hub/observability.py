from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode

from .config import HubConfig


SENSITIVE_FIELDS = {"authorization", "cookie", "set-cookie", "token", "pairing_token", "access_token"}


def _redact_mapping(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    redacted = {}
    for key, value in data.items():
        if str(key).lower() in SENSITIVE_FIELDS:
            redacted[key] = "[Filtered]"
        else:
            redacted[key] = value
    return redacted


def _redact_all_mapping_values(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    return {key: "[Filtered]" for key in data}


def _redact_query_string(query_string: Any) -> Any:
    if not isinstance(query_string, str) or not query_string:
        return query_string
    pairs = []
    for key, value in parse_qsl(query_string, keep_blank_values=True):
        pairs.append((key, "[Filtered]" if key.lower() in SENSITIVE_FIELDS else value))
    return urlencode(pairs)


def redact_sentry_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        request["headers"] = _redact_mapping(request.get("headers"))
        request["cookies"] = _redact_all_mapping_values(request.get("cookies"))
        request["query_string"] = _redact_query_string(request.get("query_string"))
    return event


def setup_sentry(config: HubConfig) -> bool:
    if not config.sentry_dsn:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=config.sentry_dsn,
        environment=config.sentry_environment or None,
        release=config.sentry_release or None,
        traces_sample_rate=config.sentry_traces_sample_rate,
        send_default_pii=config.sentry_send_default_pii,
        before_send=redact_sentry_event,
        before_send_transaction=redact_sentry_event,
    )
    sentry_sdk.set_tag("component", "hub")
    return True


def capture_exception(exc: BaseException) -> None:
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        pass
