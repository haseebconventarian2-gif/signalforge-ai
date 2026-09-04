from app.core.logging import redact_secrets


def test_secret_redaction_handles_nested_values() -> None:
    event = {
        "event": "provider_request",
        "authorization": "Bearer secret",
        "APCA-API-SECRET-KEY": "broker-secret",
        "payload": {
            "alpaca_api_key": "key",
            "safe": "visible",
            "items": [{"secret_key": "secret"}],
        },
    }

    result = redact_secrets(None, "info", event)

    assert result["authorization"] == "[REDACTED]"
    assert result["APCA-API-SECRET-KEY"] == "[REDACTED]"
    assert result["payload"]["alpaca_api_key"] == "[REDACTED]"
    assert result["payload"]["items"][0]["secret_key"] == "[REDACTED]"
    assert result["payload"]["safe"] == "visible"
