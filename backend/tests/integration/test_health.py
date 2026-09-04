from fastapi.testclient import TestClient


def test_liveness_is_versioned_and_identifies_paper_mode(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json() == {
        "status": "ok",
        "service": "SignalForge API",
        "version": "0.1.0",
        "paper_trading": True,
    }


def test_api_allows_configured_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_readiness_checks_database_without_exposing_secrets(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "connected",
        "paper_trading": True,
        "credentials_configured": False,
        "llm_configured": False,
        "order_submission_enabled": False,
    }
    body = response.text.lower()
    assert "database_url" not in body
    assert "api_key" not in body
    assert "secret" not in body


def test_openapi_and_docs_are_versioned(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").status_code == 200
    assert client.get("/api/v1/docs").status_code == 200
    assert client.get("/docs").status_code == 404


def test_alpaca_connectivity_is_read_only_and_reports_unconfigured(client: TestClient) -> None:
    response = client.get("/api/v1/integrations/alpaca/connectivity")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "connected": False,
        "paper_trading": True,
        "account_status": None,
        "market_open": None,
        "options_buying_power_available": None,
        "provider_request_ids": [],
        "message": "Alpaca paper credentials are not configured",
    }


def test_market_scan_is_read_only_and_empty_when_credentials_are_absent(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/market/opportunities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["watchlist"] == [
        "SPY",
        "QQQ",
        "IWM",
        "AAPL",
        "MSFT",
        "NVDA",
        "AMD",
        "TSLA",
        "META",
        "AMZN",
        "GOOGL",
        "NFLX",
        "AVGO",
        "JPM",
        "BAC",
        "XOM",
        "COIN",
        "PLTR",
        "INTC",
        "TLT",
    ]
    assert payload["opportunities"] == []
    assert payload["timestamp"].endswith("Z")


def test_agent_mutations_are_disabled_without_a_control_token(client: TestClient) -> None:
    response = client.post("/api/v1/agent/kill-switch")

    assert response.status_code == 503
    assert response.json()["code"] == "CONTROL_API_DISABLED"
