from hub.control_hub.config import load_config
from hub.control_hub.observability import redact_sentry_event, setup_sentry


def test_hub_sentry_config_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("CONTROL_SENTRY_DSN", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_TRACES_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("CONTROL_SENTRY_SEND_DEFAULT_PII", raising=False)

    config = load_config()

    assert config.sentry_dsn == ""
    assert config.sentry_environment == "production"
    assert config.sentry_release == ""
    assert config.sentry_traces_sample_rate == 0.0
    assert config.sentry_send_default_pii is False
    assert setup_sentry(config) is False


def test_hub_sentry_config_reads_environment(monkeypatch):
    monkeypatch.setenv("CONTROL_SENTRY_DSN", "https://example.invalid/1")
    monkeypatch.setenv("CONTROL_SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("CONTROL_SENTRY_RELEASE", "abc123")
    monkeypatch.setenv("CONTROL_SENTRY_TRACES_SAMPLE_RATE", "2")
    monkeypatch.setenv("CONTROL_SENTRY_SEND_DEFAULT_PII", "true")

    config = load_config()

    assert config.sentry_dsn == "https://example.invalid/1"
    assert config.sentry_environment == "staging"
    assert config.sentry_release == "abc123"
    assert config.sentry_traces_sample_rate == 1.0
    assert config.sentry_send_default_pii is True


def test_redact_sentry_event_filters_sensitive_request_data():
    event = {
        "request": {
            "headers": {"Authorization": "Bearer secret", "User-Agent": "pytest"},
            "cookies": {"session": "secret", "theme": "dark"},
            "query_string": "agent_id=windows&token=secret&x=1",
        }
    }

    redacted = redact_sentry_event(event, {})

    request = redacted["request"]
    assert request["headers"]["Authorization"] == "[Filtered]"
    assert request["headers"]["User-Agent"] == "pytest"
    assert request["cookies"]["session"] == "[Filtered]"
    assert request["cookies"]["theme"] == "[Filtered]"
    assert request["query_string"] == "agent_id=windows&token=%5BFiltered%5D&x=1"
