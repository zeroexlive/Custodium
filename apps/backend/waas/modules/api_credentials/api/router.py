from __future__ import annotations

from ninja import Router, Status
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth, HMACAuth, require_scopes
from waas.common.pagination import paginated
from waas.modules.api_credentials.api.schemas import ApiKeyIn, api_key_out
from waas.modules.api_credentials.models import ALLOWED_SCOPES, ApiKey
from waas.modules.audit.models import AuditEvent
from waas.modules.organizations.api.router import WRITE_ROLES
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project
from waas.security.secret_management.crypto import encrypt_secret

router = Router(tags=["api-credentials"])
dashboard_auth = DashboardAuth()
hmac_auth = HMACAuth()


def _project_for_member(user: object, project_id: str, *, write: bool) -> Project:
    project = (
        Project.objects.select_related("organization")
        .filter(id=project_id, organization__memberships__user=user)
        .first()
    )
    if project is None:
        raise HttpError(404, "Project not found")
    if write:
        membership = Membership.objects.filter(user=user, organization=project.organization).first()
        if membership is None or membership.role not in WRITE_ROLES:
            raise HttpError(403, "Your role cannot manage API credentials")
    return project


def _create_key(project: Project, user: object, name: str, scopes: list[str],
                rotated_from: ApiKey | None = None) -> tuple[ApiKey, str]:
    invalid = [s for s in scopes if s not in ALLOWED_SCOPES]
    if invalid:
        raise HttpError(422, f"Unknown scopes: {', '.join(invalid)}")
    secret = ApiKey.generate_secret()
    key = ApiKey.objects.create(
        project=project, name=name, key_id=ApiKey.generate_key_id(project.environment),
        secret_ciphertext=encrypt_secret(secret), scopes=scopes,
        created_by=user, rotated_from=rotated_from,
    )
    return key, secret


@router.post("/api-keys", response={201: dict}, auth=dashboard_auth)
def create_api_key(request, payload: ApiKeyIn):
    project = _project_for_member(request.auth, payload.project_id, write=True)
    name = payload.name.strip()
    if not name:
        raise HttpError(422, "API key name is required")
    key, secret = _create_key(project, request.auth, name, payload.scopes)
    AuditEvent.record(
        "api_key.created", actor_user=request.auth,
        organization=project.organization, project=project, api_key=key,
        metadata={"scopes": payload.scopes},
    )
    result = api_key_out(key)
    result["secret"] = secret  # shown exactly once — never stored client-side
    return Status(201, result)


@router.get("/api-keys", response=dict, auth=dashboard_auth)
def list_api_keys(request, project_id: str | None = None):
    keys = (
        ApiKey.objects.filter(project__organization__memberships__user=request.auth)
        .order_by("-created_at")
        .distinct()
    )
    if project_id:
        keys = keys.filter(project_id=project_id)
    return paginated(api_key_out(k) for k in keys)


@router.post("/api-keys/{key_id}/rotate", response={201: dict}, auth=dashboard_auth)
def rotate_api_key(request, key_id: str):
    old = (
        ApiKey.objects.select_related("project", "project__organization")
        .filter(id=key_id, project__organization__memberships__user=request.auth)
        .first()
    )
    if old is None:
        raise HttpError(404, "API key not found")
    _project_for_member(request.auth, str(old.project_id), write=True)
    if old.status != ApiKey.Status.ACTIVE:
        raise HttpError(409, "Only an active API key can be rotated")
    new_key, secret = _create_key(old.project, request.auth, old.name, list(old.scopes), rotated_from=old)
    old.revoke()
    AuditEvent.record(
        "api_key.rotated", actor_user=request.auth,
        organization=old.project.organization, project=old.project, api_key=new_key,
    )
    result = api_key_out(new_key)
    result["secret"] = secret
    return Status(201, result)


@router.post("/api-keys/{key_id}/revoke", response=dict, auth=dashboard_auth)
def revoke_api_key(request, key_id: str):
    key = (
        ApiKey.objects.select_related("project", "project__organization")
        .filter(id=key_id, project__organization__memberships__user=request.auth)
        .first()
    )
    if key is None:
        raise HttpError(404, "API key not found")
    _project_for_member(request.auth, str(key.project_id), write=True)
    if key.status == ApiKey.Status.ACTIVE:
        key.revoke()
        AuditEvent.record(
            "api_key.revoked", actor_user=request.auth,
            organization=key.project.organization, project=key.project, api_key=key,
        )
    return {"detail": "API key revoked"}


@router.get("/machine/whoami", response=dict, auth=hmac_auth)
def machine_whoami(request):
    """Phase 1 acceptance endpoint: proves tenant context is derived from the
    HMAC-authenticated credential, never from client-supplied identifiers."""
    if not require_scopes(request, "read"):
        raise HttpError(403, "Missing required scope: read")
    key: ApiKey = request.auth
    AuditEvent.record(
        "api.machine_whoami", organization=key.project.organization,
        project=key.project, api_key=key,
    )
    return {
        "key_id": key.key_id,
        "project_id": str(key.project_id),
        "organization_id": str(key.project.organization_id),
        "environment": key.project.environment,
        "scopes": list(key.scopes),
    }
