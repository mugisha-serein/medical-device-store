"""HTTP contracts affected by the FastAPI and Starlette upgrade."""

import hashlib
import json

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", [None, "text/plain", "application/json"])
async def test_refresh_requires_json_content_type(client, content_type):
    headers = {"Content-Type": content_type} if content_type else {}
    response = await client.post(
        "/api/v1/auth/refresh",
        content='{"refresh_token":"invalid-token"}',
        headers=headers,
    )

    if content_type == "application/json":
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or expired token"}
        assert response.headers["WWW-Authenticate"] == "Bearer"
    else:
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][0] == "body"


@pytest.mark.asyncio
async def test_cors_preflight_preserves_auth_headers(client):
    origin = "https://storefront.example.test"
    response = await client.options("/api/v1/auth/login", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "Origin" in response.headers["Vary"]
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert {"authorization", "content-type"} <= {
        name.strip().lower() for name in response.headers["Access-Control-Allow-Headers"].split(",")
    }


@pytest.mark.asyncio
async def test_openapi_matches_baseline_except_validation_error_fields(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    properties = schema["components"]["schemas"]["ValidationError"]["properties"]
    assert properties.pop("ctx") == {"title": "Context", "type": "object"}
    assert properties.pop("input") == {"title": "Input"}

    # Digests of canonical JSON from the unmodified 3bcef594 FastAPI 0.115.6 app.
    # Separate checks identify whether a route or a shared schema changed.
    baseline_digests = {
        "paths": "85d7bf9ce20448c72587b1de7216a811a11dd0ea346ab156397b99e07e9a2d47",
        "components": "3378b2ee132cde144809b2b6850d9ad110e3bd09bfe5c523676fd556c9b0f410",
    }
    for section, expected in baseline_digests.items():
        serialized = json.dumps(schema[section], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert hashlib.sha256(serialized.encode("utf-8")).hexdigest() == expected, section
