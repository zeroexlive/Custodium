from __future__ import annotations

import json
import time
import uuid

import pytest
from django.test import Client

from waas.security.hmac.signing import sign as hmac_sign

PASSWORD = "Str0ng!Passw0rd"


def register_user(client: Client, email: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        data=json.dumps({"email": email, "password": PASSWORD, "display_name": "Test"}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def auth_headers(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def make_org_project(client: Client, token: str, email_suffix: str = "") -> dict:
    org_resp = client.post(
        "/api/v1/organizations",
        data=json.dumps({"name": f"Acme {email_suffix}"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert org_resp.status_code == 201, org_resp.content
    org = org_resp.json()
    project_resp = client.post(
        "/api/v1/projects",
        data=json.dumps(
            {"organization_id": org["id"], "name": "Main", "environment": "sandbox"}
        ),
        content_type="application/json",
        **auth_headers(token),
    )
    assert project_resp.status_code == 201, project_resp.content
    return {"organization": org, "project": project_resp.json()}


def make_api_key(client: Client, token: str, project_id: str, scopes: list[str] | None = None) -> dict:
    response = client.post(
        "/api/v1/api-keys",
        data=json.dumps({"project_id": project_id, "name": "server", "scopes": scopes or ["read"]}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert response.status_code == 201, response.content
    return response.json()


def hmac_headers(secret: str, key_id: str, method: str, path: str, body: bytes = b"",
                 nonce: str | None = None, timestamp: int | None = None) -> dict:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or uuid.uuid4().hex
    signature = hmac_sign(secret, method, path, ts, nonce, body)
    return {
        "HTTP_X_API_KEY_ID": key_id,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_X_TIMESTAMP": ts,
        "HTTP_X_NONCE": nonce,
    }


@pytest.fixture()
def client() -> Client:
    return Client()
