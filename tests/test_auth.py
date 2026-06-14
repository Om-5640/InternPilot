"""Module 0 auth acceptance tests.

Covers:
- signup returns user + token + refresh_token; user shape matches contract; no password_hash
- duplicate email → 409
- wrong password → 401
- GET /auth/me with valid token → user
- GET /auth/me with no/invalid token → 401
- refresh returns a new access token
- consent update persists + returns updated user
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

SIGNUP_URL = "/api/auth/signup"
LOGIN_URL = "/api/auth/login"
ME_URL = "/api/auth/me"
REFRESH_URL = "/api/auth/refresh"
CONSENT_URL = "/api/auth/consent"

USER_FIELDS = {"id", "name", "email", "role", "auth_provider", "consent", "created_at"}
CONSENT_FIELDS = {"gmail", "github", "alumni_data"}


def _check_user_shape(user: dict) -> None:
    assert set(user.keys()) == USER_FIELDS, f"Unexpected user fields: {set(user.keys())}"
    assert "password_hash" not in user
    assert user["role"] in ("student", "admin")
    assert user["auth_provider"] in ("password", "google")
    assert set(user["consent"].keys()) == CONSENT_FIELDS
    assert isinstance(user["consent"]["gmail"], bool)
    assert isinstance(user["consent"]["github"], bool)
    assert isinstance(user["consent"]["alumni_data"], bool)


# ---------------------------------------------------------------------------
# signup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_returns_correct_shape(client: AsyncClient) -> None:
    resp = await client.post(
        SIGNUP_URL,
        json={"name": "Alice", "email": "alice@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "user" in body
    assert "token" in body
    assert "refresh_token" in body
    _check_user_shape(body["user"])
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["name"] == "Alice"
    assert body["user"]["role"] == "student"
    assert body["user"]["auth_provider"] == "password"


@pytest.mark.asyncio
async def test_signup_duplicate_email_returns_409(client: AsyncClient) -> None:
    payload = {"name": "Bob", "email": "bob@example.com", "password": "password123"}
    r1 = await client.post(SIGNUP_URL, json=payload)
    assert r1.status_code == 201

    r2 = await client.post(SIGNUP_URL, json=payload)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.asyncio
async def test_signup_no_password_hash_in_response(client: AsyncClient) -> None:
    resp = await client.post(
        SIGNUP_URL,
        json={"name": "Carol", "email": "carol@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    body_str = resp.text
    assert "password_hash" not in body_str
    assert "argon" not in body_str.lower()


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_correct_credentials(client: AsyncClient) -> None:
    await client.post(
        SIGNUP_URL,
        json={"name": "Dave", "email": "dave@example.com", "password": "mypassword"},
    )
    resp = await client.post(
        LOGIN_URL,
        json={"email": "dave@example.com", "password": "mypassword"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body and "refresh_token" in body
    _check_user_shape(body["user"])


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    await client.post(
        SIGNUP_URL,
        json={"name": "Eve", "email": "eve@example.com", "password": "correct-password"},
    )
    resp = await client.post(
        LOGIN_URL,
        json={"email": "eve@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        LOGIN_URL,
        json={"email": "nobody@example.com", "password": "irrelevant"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_with_valid_token(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.get(ME_URL, headers=auth_headers)
    assert resp.status_code == 200
    _check_user_shape(resp.json()["user"])


@pytest.mark.asyncio
async def test_me_no_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get(ME_URL)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get(ME_URL, headers={"Authorization": "Bearer not.a.valid.token"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_returns_new_token(client: AsyncClient) -> None:
    signup = await client.post(
        SIGNUP_URL,
        json={"name": "Frank", "email": "frank@example.com", "password": "frankpassword"},
    )
    assert signup.status_code == 201
    refresh_token = signup.json()["refresh_token"]

    resp = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(client: AsyncClient) -> None:
    signup = await client.post(
        SIGNUP_URL,
        json={"name": "Grace", "email": "grace@example.com", "password": "gracepass1"},
    )
    access_token = signup.json()["token"]
    resp = await client.post(REFRESH_URL, json={"refresh_token": access_token})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# consent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consent_update_persists(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.put(
        CONSENT_URL,
        json={"gmail": True, "alumni_data": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    user = resp.json()["user"]
    _check_user_shape(user)
    assert user["consent"]["gmail"] is True
    assert user["consent"]["alumni_data"] is True
    assert user["consent"]["github"] is False  # untouched


@pytest.mark.asyncio
async def test_consent_partial_update(client: AsyncClient, auth_headers: dict) -> None:
    await client.put(CONSENT_URL, json={"gmail": True}, headers=auth_headers)
    resp = await client.put(CONSENT_URL, json={"github": True}, headers=auth_headers)
    assert resp.status_code == 200
    consent = resp.json()["user"]["consent"]
    # gmail should still be True from the first update (persisted in DB + returned)
    assert consent["github"] is True
