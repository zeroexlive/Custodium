"""Phase 1 acceptance: register -> verify -> org -> project -> API key ->
authenticated HMAC machine request, with tenant context derived server-side."""
from __future__ import annotations

import json

import pytest
from django.test import Client

from tests.conftest import auth_headers, hmac_headers, make_api_key, make_org_project, register_user

pytestmark = pytest.mark.django_db


def test_full_phase1_flow(client: Client) -> None:
    data = register_user(client, "owner@example.com")
    token = data["access_token"]

    me = client.get("/api/v1/me", **auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"
    assert me.json()["is_email_verified"] is False

    verify = client.post(
        "/api/v1/auth/verify-email",
        data=json.dumps({"token": data["verification_token"]}),
        content_type="application/json",
    )
    assert verify.status_code == 200
    me = client.get("/api/v1/me", **auth_headers(token))
    assert me.json()["is_email_verified"] is True

    ctx = make_org_project(client, token)
    key = make_api_key(client, token, ctx["project"]["id"], scopes=["read"])
    assert key["key_id"].startswith("ck_test_")
    assert key["secret"]

    path = "/api/v1/machine/whoami"
    resp = client.get(path, **hmac_headers(key["secret"], key["key_id"], "GET", path))
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["project_id"] == ctx["project"]["id"]
    assert body["organization_id"] == ctx["organization"]["id"]
    assert body["environment"] == "sandbox"


def test_login_and_logout(client: Client) -> None:
    register_user(client, "login@example.com")
    login = client.post(
        "/api/v1/auth/login",
        data=json.dumps({"email": "login@example.com", "password": "Str0ng!Passw0rd"}),
        content_type="application/json",
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert client.get("/api/v1/me", **auth_headers(token)).status_code == 200
    assert client.post("/api/v1/auth/logout", **auth_headers(token)).status_code == 200
    assert client.get("/api/v1/me", **auth_headers(token)).status_code == 401


def test_register_duplicate_email_rejected(client: Client) -> None:
    register_user(client, "dup@example.com")
    resp = client.post(
        "/api/v1/auth/register",
        data=json.dumps({"email": "dup@example.com", "password": "Str0ng!Passw0rd"}),
        content_type="application/json",
    )
    assert resp.status_code == 409


def test_unauthenticated_requests_rejected(client: Client) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/organizations").status_code == 401
    assert client.get("/api/v1/networks").status_code == 401
