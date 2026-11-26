from datetime import datetime, timezone

import jwt
import pytest
from httpx import AsyncClient


# Captured from python-jose 3.5.0 with this synthetic key and a fixed subject.
# The fixtures remain usable without installing the retired library.
LEGACY_KEY = "fixture-only-jwt-signing-key-for-compatibility-tests"
LEGACY_SUB = "10000000-0000-4000-8000-000000000042"
LEGACY_ACCESS = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMDAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAwNDIiLCJleHAiOjQxMDI0NDQ4MDAsInR5cGUiOiJhY2Nlc3MiLCJpc19hZG1pbiI6dHJ1ZX0."
    "5nnnTqxCAMhsFRsdqZvkieDNe4s351eUvclo50sh2UY"
)
LEGACY_REFRESH = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMDAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAwNDIiLCJleHAiOjQxMDI0NDQ4MDAsInR5cGUiOiJyZWZyZXNoIn0."
    "nkuVCJExy7xChhCMd_QCkQ8XpNdifskfg4g7ZZ1RWB0"
)


@pytest.fixture
def jwt_settings(monkeypatch):
    from app.core import security

    monkeypatch.setattr(security.settings, "JWT_SECRET_KEY", LEGACY_KEY)
    monkeypatch.setattr(security.settings, "JWT_ALGORITHM", "HS256")
    return security.settings


@pytest.mark.parametrize("kind", ["access", "refresh"])
def test_token_creation_preserves_claims_algorithm_and_lifetime(kind, jwt_settings, monkeypatch):
    from app.core import security

    monkeypatch.setattr(jwt_settings, "JWT_ALGORITHM", "HS384")
    expires_in = (
        jwt_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60 if kind == "access"
        else jwt_settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    )
    claims = {"sub": LEGACY_SUB}
    if kind == "access":
        claims["is_admin"] = True
    sign = security.create_access_token if kind == "access" else security.create_refresh_token
    before = int(datetime.now(timezone.utc).timestamp())
    token = sign(claims)
    after = int(datetime.now(timezone.utc).timestamp())
    verified = jwt.decode(token, LEGACY_KEY, algorithms=["HS384"])
    expires_at = verified.pop("exp")

    assert jwt.get_unverified_header(token)["alg"] == "HS384"
    assert verified == {**claims, "type": kind}
    assert before + expires_in <= expires_at <= after + expires_in


@pytest.mark.asyncio
async def test_legacy_access_and_refresh_tokens_remain_usable(client, db_session, jwt_settings):
    from app.core import security
    from app.identity.models import User

    db_session.add(User(
        id=LEGACY_SUB, email="legacy@example.test", name="Legacy Admin",
        password_hash=security.hash_password("fixture-password"), is_admin=True,
    ))
    await db_session.commit()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {LEGACY_ACCESS}"})
    assert me.status_code == 200
    assert me.json()["id"] == LEGACY_SUB
    assert security.decode_token(LEGACY_ACCESS)["is_admin"] is True

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": LEGACY_REFRESH})
    assert refreshed.status_code == 200
    assert security.decode_token(refreshed.json()["access_token"])["sub"] == LEGACY_SUB
    assert security.decode_token(refreshed.json()["access_token"])["is_admin"] is True
    assert security.decode_token(refreshed.json()["refresh_token"])["type"] == "refresh"


def token_for_case(case, subject=LEGACY_SUB):
    claims = {"sub": subject, "exp": 4102444800, "type": "access", "is_admin": True}
    key = LEGACY_KEY
    algorithm = "HS256"
    overrides = {
        "expired": {"exp": 1},
        "wrong-type": {"type": "refresh"},
        "wrong-type-format": {"type": ["access"]},
        "invalid-exp": {"exp": "4102444800"},
        "null-exp": {"exp": None},
        "boolean-exp": {"exp": True},
        "invalid-sub": {"sub": 123},
        "empty-sub": {"sub": ""},
        "invalid-admin": {"is_admin": "true"},
        "ordinary-user": {"is_admin": False},
    }
    if case in overrides:
        claims.update(overrides[case])
    elif case == "missing-sub":
        del claims["sub"]
    elif case == "missing-exp":
        del claims["exp"]
    elif case == "wrong-algorithm":
        algorithm = "HS384"
    elif case == "unsigned":
        key, algorithm = "", "none"
    elif case == "wrong-key":
        key = "another-synthetic-signing-key-with-at-least-32-bytes"
    elif case == "malformed":
        return "malformed"
    elif case == "modified-signature":
        payload, signature = jwt.encode(claims, key, algorithm=algorithm).rsplit(".", 1)
        different = "B" if signature[0] == "A" else "A"
        return f"{payload}.{different}{signature[1:]}"
    return jwt.encode(claims, key, algorithm=algorithm)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "expired", "modified-signature", "malformed", "wrong-algorithm", "missing-sub",
    "wrong-type", "wrong-type-format", "invalid-exp", "null-exp", "boolean-exp", "missing-exp",
    "unsigned", "wrong-key", "invalid-sub", "empty-sub", "invalid-admin",
])
async def test_protected_endpoint_rejects_invalid_jwt(client, test_user, jwt_settings, case):
    token = token_for_case(case, test_user.id)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    if case not in {"missing-sub", "wrong-type", "wrong-type-format"}:
        assert response.json()["detail"] == "Invalid or expired token"
        assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_access_token_cannot_be_used_as_refresh(client, jwt_settings):
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": LEGACY_ACCESS})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token type."


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "valid-admin", "disabled-policy", "ordinary-user", "expired", "wrong-key", "wrong-algorithm",
    "malformed", "malformed-header", "unsigned", "invalid-admin", "missing-sub", "wrong-type",
])
async def test_login_rate_limit_bypasses_only_verified_admin_access(client, jwt_settings, monkeypatch, case):
    from app.core import rate_limit

    monkeypatch.setattr(jwt_settings, "JWT_ADMIN_BYPASS", case != "disabled-policy")
    token = LEGACY_ACCESS if case in {"valid-admin", "disabled-policy"} else token_for_case(case)
    authorization = "Bearer" if case == "malformed-header" else f"Bearer {token}"
    path = "/api/v1/auth/login"
    responses = [
        await client.post(path, headers={"Authorization": authorization}, json={
            "email": f"absent{index}@example.com", "password": "fixture-password",
        })
        for index in range(6)
    ]
    bypassed = case == "valid-admin"
    assert [response.status_code for response in responses] == [401] * 5 + [401 if bypassed else 429]
    cache = await rate_limit._get_redis()
    assert await cache.zcard(f"rl:127.0.0.1:{path}") == (0 if bypassed else 6)


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "New User",
            "email": "new@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "new@example.com"
    assert data["user"]["name"] == "New User"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"name": "User 1", "email": "dup@example.com", "password": "password123"},
    )
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "User 2", "email": "dup@example.com", "password": "password456"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "User", "email": "weak@example.com", "password": "short"},
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Login User", "email": "login@example.com", "password": "password123"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"name": "User", "email": "wrong@example.com", "password": "password123"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrong@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, auth_headers: dict):
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={
            "current_password": "testpass123",
            "new_password": "newpassword123",
        },
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_change_password_wrong_current(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={
            "current_password": "wrongpassword",
            "new_password": "newpassword123",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient):
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Refresh User", "email": "refresh@example.com", "password": "password123"},
    )
    refresh_token = register_response.json()["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
