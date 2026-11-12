"""HMAC machine authentication: signature, replay, expiry, revocation, scopes."""
from __future__ import annotations

import time

import pytest
from django.test import Client

from tests.conftest import hmac_headers, make_api_key, make_org_project, register_user

pytestmark = pytest.mark.django_db
PATH = "/api/v1/machine/whoami"


@pytest.fixture()
def key(client: Client) -> dict:
    user = register_user(client, "hmac@example.com")
    ctx = make_org_project(client, user["access_token"])
    created = make_api_key(client, user["access_token"], ctx["project"]["id"], scopes=["read"])
    created["_dashboard_token"] = user["access_token"]
    return created


def test_valid_signature_accepted(client: Client, key: dict) -> None:
    resp = client.get(PATH, **hmac_headers(key["secret"], key["key_id"], "GET", PATH))
    assert resp.status_code == 200


def test_bad_signature_rejected(client: Client, key: dict) -> None:
    headers = hmac_headers(key["secret"], key["key_id"], "GET", PATH)
    headers["HTTP_X_SIGNATURE"] = "0" * 64
    assert client.get(PATH, **headers).status_code == 401


def test_replayed_nonce_rejected(client: Client, key: dict) -> None:
    headers = hmac_headers(key["secret"], key["key_id"], "GET", PATH, nonce="fixed-nonce-1")
    assert client.get(PATH, **headers).status_code == 200
    assert client.get(PATH, **headers).status_code == 401


def test_stale_timestamp_rejected(client: Client, key: dict) -> None:
    stale = int(time.time()) - 3600
    headers = hmac_headers(key["secret"], key["key_id"], "GET", PATH, timestamp=stale)
    assert client.get(PATH, **headers).status_code == 401


def test_revoked_key_rejected(client: Client, key: dict) -> None:
    from tests.conftest import auth_headers

    resp = client.post(
        f"/api/v1/api-keys/{key['id']}/revoke", **auth_headers(key["_dashboard_token"])
    )
    assert resp.status_code == 200
    headers = hmac_headers(key["secret"], key["key_id"], "GET", PATH)
    assert client.get(PATH, **headers).status_code == 401


def test_rotated_key_old_secret_rejected_new_accepted(client: Client, key: dict) -> None:
    from tests.conftest import auth_headers

    rotated = client.post(
        f"/api/v1/api-keys/{key['id']}/rotate", **auth_headers(key["_dashboard_token"])
    )
    assert rotated.status_code == 201, rotated.content
    new_key = rotated.json()
    old_headers = hmac_headers(key["secret"], key["key_id"], "GET", PATH)
    assert client.get(PATH, **old_headers).status_code == 401
    new_headers = hmac_headers(new_key["secret"], new_key["key_id"], "GET", PATH)
    assert client.get(PATH, **new_headers).status_code == 200


def test_secret_never_listed(client: Client, key: dict) -> None:
    from tests.conftest import auth_headers

    listed = client.get("/api/v1/api-keys", **auth_headers(key["_dashboard_token"]))
    assert listed.status_code == 200
    assert key["secret"] not in listed.content.decode()
    for item in listed.json()["items"]:
        assert "secret" not in item
        assert "secret_ciphertext" not in item
