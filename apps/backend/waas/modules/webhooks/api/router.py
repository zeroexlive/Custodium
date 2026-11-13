"""Phase 11 webhooks API: endpoint management (dashboard),
delivery inspection, and replay. Machine keys may also manage
endpoints with the `webhooks:manage` scope."""

from __future__ import annotations

from ninja import Router, Schema
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.modules.audit.models import AuditEvent
from waas.modules.organizations.models import Membership
from waas.modules.sweeps.resolver import ResolutionError

from .. import services
from ..models import EVENT_TYPES, WebhookDelivery, WebhookEndpoint

router = Router(tags=["webhooks"], auth=AnyAuth())
dashboard_router = Router(tags=["webhooks-dashboard"], auth=DashboardAuth())

ADMIN_ROLES = {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR}


class EndpointIn(Schema):
    project_id: str
    url: str
    events: list[str] = []
    enabled: bool = True


def _authorize_write(request, project) -> None:
    if is_machine(request):
        if str(request.api_key.project_id) != str(project.id):
            raise HttpError(404, "project not found")
        if not has_any_scope(request, "webhooks:manage"):
            raise HttpError(403, "missing scope: webhooks:manage")
        return
    membership = Membership.objects.filter(
        organization=project.organization, user=request.actor
    ).first()
    if membership is None:
        raise HttpError(404, "project not found")
    if membership.role not in ADMIN_ROLES:
        raise HttpError(403, "webhook management requires an owner or administrator")


def _out(endpoint: WebhookEndpoint) -> dict:
    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "events": endpoint.events,
        "enabled": endpoint.enabled,
        "created_at": endpoint.created_at.isoformat(),
    }


@router.post(
    "/webhooks/endpoints", response={201: dict, 403: dict, 404: dict, 422: dict}
)
def create_endpoint(request, payload: EndpointIn):
    project = resolve_project(request, payload.project_id) if not is_machine(request) else None
    if is_machine(request):
        from waas.modules.projects.models import Project

        project = Project.objects.filter(id=request.api_key.project_id).first()
        if project is None:
            raise HttpError(404, "project not found")
    _authorize_write(request, project)
    bad = [event for event in payload.events if event not in EVENT_TYPES]
    if bad:
        raise HttpError(422, f"unknown event type(s): {', '.join(bad)}")
    try:
        endpoint, secret = services.create_endpoint(
            project=project, url=payload.url, events=payload.events, enabled=payload.enabled
        )
    except ResolutionError as exc:
        raise HttpError(422, f"{exc.stage}: {exc.message}") from exc
    return 201, {**_out(endpoint), "signing_secret": secret}


@router.get("/webhooks/endpoints", response={200: list[dict], 404: dict})
def list_endpoints(request, project_id: str = ""):
    if is_machine(request):
        project_ids = [request.api_key.project_id]
    else:
        project = resolve_project(request, project_id or None)
        project_ids = [project.id]
    return [
        _out(endpoint)
        for endpoint in WebhookEndpoint.objects.filter(project_id__in=project_ids)
    ]


@router.delete("/webhooks/endpoints/{endpoint_id}", response={200: dict, 404: dict})
def delete_endpoint(request, endpoint_id: str):
    endpoint = WebhookEndpoint.objects.filter(id=endpoint_id).select_related("project").first()
    if endpoint is None:
        raise HttpError(404, "endpoint not found")
    _authorize_write(request, endpoint.project)
    endpoint.enabled = False
    endpoint.save(update_fields=["enabled", "updated_at"])
    return _out(endpoint)


@router.post(
    "/webhooks/endpoints/{endpoint_id}/rotate-secret",
    response={200: dict, 403: dict, 404: dict},
)
def rotate_endpoint_secret(request, endpoint_id: str):
    """Replace the endpoint's signing secret (shown once). The
    old secret stops verifying immediately."""
    endpoint = WebhookEndpoint.objects.filter(id=endpoint_id).select_related("project").first()
    if endpoint is None:
        raise HttpError(404, "endpoint not found")
    _authorize_write(request, endpoint.project)
    secret = services.rotate_signing_secret(endpoint=endpoint)
    AuditEvent.record(
        "webhook.secret_rotated",
        organization=endpoint.project.organization, project=endpoint.project,
        metadata={"endpoint_id": str(endpoint.id)},
    )
    return {**_out(endpoint), "signing_secret": secret}


@router.get("/webhooks/deliveries", response={200: list[dict], 404: dict})
def list_deliveries(request, project_id: str = ""):
    if is_machine(request):
        project_ids = [request.api_key.project_id]
    else:
        project = resolve_project(request, project_id or None)
        project_ids = [project.id]
    deliveries = (
        WebhookDelivery.objects.filter(event__project_id__in=project_ids)
        .select_related("event", "endpoint")
        .order_by("-created_at")[:200]
    )
    return [
        {
            "id": str(delivery.id),
            "event_id": str(delivery.event_id),
            "event_type": delivery.event.event_type,
            "endpoint_url": delivery.endpoint.url,
            "status": delivery.status,
            "attempts": delivery.attempts,
            "last_status_code": delivery.last_status_code,
            "last_error": delivery.last_error,
            "next_attempt_at": (
                delivery.next_attempt_at.isoformat() if delivery.next_attempt_at else None
            ),
            "delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
        }
        for delivery in deliveries
    ]


@dashboard_router.post(
    "/webhooks/deliveries/{delivery_id}/replay", response={200: dict, 403: dict, 404: dict}
)
def replay_delivery(request, delivery_id: str):
    delivery = (
        WebhookDelivery.objects.filter(id=delivery_id)
        .select_related("event__project")
        .first()
    )
    if delivery is None:
        raise HttpError(404, "delivery not found")
    _authorize_write(request, delivery.event.project)
    services.replay_delivery(delivery)
    return {"id": str(delivery.id), "status": delivery.status}
