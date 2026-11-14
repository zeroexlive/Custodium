"""Phase 1 acceptance: admin-created account -> verify -> org ->
project -> API key -> authenticated HMAC machine request, with
tenant context derived server-side. Public registration does not
exist: only the platform owner / global administrators create
customer accounts."""
from __future__ import annotations

import json

import pytest
from django.core import mail
from django.test import Client

from tests.conftest import PASSWORD, auth_headers, hmac_headers, make_api_key, make_org_project, register_user

pytestmark = pytest.mark.django_db


def _staff_token(email: str = "admin@example.com") -> tuple[object, str]:
    from waas.modules.identity.models import DashboardToken, User

    admin = User.objects.create_user(email=email, password=PASSWORD, is_staff=True)
    _, raw = DashboardToken.issue(admin)
    return admin, raw


def test_full_phase1_flow(client: Client) -> None:
    data = register_user(client, "owner@example.com")
    token = data["access_token"]

    me = client.get("/api/v1/me", **auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"
    assert me.json()["is_email_verified"] is False

    from waas.modules.identity.models import OneTimeToken, User

    user = User.objects.get(email="owner@example.com")
    _, verification_raw = OneTimeToken.issue(user, OneTimeToken.Purpose.EMAIL_VERIFICATION, 24)
    verify = client.post(
        "/api/v1/auth/verify-email",
        data=json.dumps({"token": verification_raw}),
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


def test_public_registration_does_not_exist(client: Client) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        data=json.dumps({"email": "walkin@example.com", "password": "Str0ng!Passw0rd"}),
        content_type="application/json",
    )
    assert resp.status_code == 404
    from waas.modules.identity.models import User

    assert not User.objects.filter(email="walkin@example.com").exists()


def test_only_platform_admins_create_customers(client: Client) -> None:
    _, admin_token = _staff_token()
    customer = register_user(client, "plain@example.com")
    payload = json.dumps({"email": "customer@example.com", "display_name": "Customer One"})

    # Unauthenticated and non-admin callers are refused.
    assert client.post("/api/v1/admin/customers", data=payload, content_type="application/json").status_code == 401
    forbidden = client.post(
        "/api/v1/admin/customers", data=payload, content_type="application/json",
        **auth_headers(customer["access_token"]),
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/v1/admin/customers", data=payload, content_type="application/json",
        **auth_headers(admin_token),
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["email"] == "customer@example.com"
    assert body["is_email_verified"] is True
    temporary_password = body["temporary_password"]
    assert temporary_password

    # Credentials were emailed to the customer (locmem backend).
    assert body["credentials_email_sent"] is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["customer@example.com"]
    assert temporary_password in mail.outbox[0].body

    # The customer can log in with the delivered credentials — and
    # only log in; account creation stays admin-only.
    login = client.post(
        "/api/v1/auth/login",
        data=json.dumps({"email": "customer@example.com", "password": temporary_password}),
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    assert login.json()["user"]["email"] == "customer@example.com"

    # Duplicate creation is a conflict; the list is admin-only too.
    duplicate = client.post(
        "/api/v1/admin/customers", data=payload, content_type="application/json",
        **auth_headers(admin_token),
    )
    assert duplicate.status_code == 409
    listing = client.get("/api/v1/admin/customers", **auth_headers(admin_token))
    assert listing.status_code == 200
    emails = {row["email"] for row in listing.json()["items"]}
    assert "customer@example.com" in emails
    assert client.get(
        "/api/v1/admin/customers", **auth_headers(customer["access_token"])
    ).status_code == 403


def test_unauthenticated_requests_rejected(client: Client) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/organizations").status_code == 401
    assert client.get("/api/v1/networks").status_code == 401
