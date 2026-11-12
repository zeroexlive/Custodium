"""Cross-tenant isolation: a user must never see or act on another tenant's
organizations, projects or API keys — and existence must not leak."""
from __future__ import annotations

import json

import pytest
from django.test import Client

from tests.conftest import auth_headers, make_api_key, make_org_project, register_user

pytestmark = pytest.mark.django_db


def test_other_tenant_cannot_see_org_project_or_keys(client: Client) -> None:
    alice = register_user(client, "alice@example.com")
    bob = register_user(client, "bob@example.com")
    ctx = make_org_project(client, alice["access_token"])
    key = make_api_key(client, alice["access_token"], ctx["project"]["id"])
    bob_headers = auth_headers(bob["access_token"])

    orgs = client.get("/api/v1/organizations", **bob_headers)
    assert orgs.json()["items"] == []
    projects = client.get("/api/v1/projects", **bob_headers)
    assert projects.json()["items"] == []

    direct = client.get(f"/api/v1/organizations/{ctx['organization']['id']}", **bob_headers)
    assert direct.status_code == 404  # no existence oracle

    create_project = client.post(
        "/api/v1/projects",
        data=json.dumps({"organization_id": ctx["organization"]["id"],
                         "name": "evil", "environment": "sandbox"}),
        content_type="application/json", **bob_headers,
    )
    assert create_project.status_code == 404

    create_key = client.post(
        "/api/v1/api-keys",
        data=json.dumps({"project_id": ctx["project"]["id"], "name": "evil", "scopes": ["read"]}),
        content_type="application/json", **bob_headers,
    )
    assert create_key.status_code == 404

    revoke = client.post(f"/api/v1/api-keys/{key['id']}/revoke", **bob_headers)
    assert revoke.status_code == 404
    keys = client.get("/api/v1/api-keys", **bob_headers)
    assert keys.json()["items"] == []
