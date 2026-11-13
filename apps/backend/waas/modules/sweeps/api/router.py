"""Phase 10 sweeps API: endpoint registration (dashboard,
owner/administrator), the resolution test tool, history, and the
sweep endpoints.

`POST /sweeps` parses the raw JSON object itself: the closed
schema rejects unknown fields, and `destination_address` /
`destination_endpoint_url` are rejected loudly with 422
(destination_not_allowed) — never silently ignored
(sweep-resolver.md §3).
"""

from __future__ import annotations

from ninja import Body, Router, Schema
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.modules.assets.models import Asset
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

from .. import resolver, services
from ..models import (
    AutoSweepRule,
    StaticSweepDestination,
    Sweep,
    SweepDestinationEndpoint,
    SweepPolicy,
)

router = Router(tags=["sweeps"], auth=AnyAuth())
dashboard_router = Router(tags=["sweeps-dashboard"], auth=DashboardAuth())

FORBIDDEN_DESTINATION_FIELDS = {"destination_address", "destination_endpoint_url"}
ALLOWED_SWEEP_FIELDS = {
    "wallet_id", "network", "asset_id", "project_id", "external_reference",
}


class EndpointIn(Schema):
    project_id: str
    endpoint_url: str | None = None
    url: str | None = None
    enabled: bool = True
    signing_secret: str = ""


class EndpointTestIn(Schema):
    project_id: str
    network: str
    asset_id: str | None = None


class ApprovalIn(Schema):
    note: str = ""


class AutoRuleIn(Schema):
    wallet_id: str
    network: str  # network slug
    asset_id: str
    threshold_amount: str  # integer base units, as a string
    enabled: bool = True


def _auto_rule_out(rule: AutoSweepRule) -> dict:
    return {
        "id": str(rule.id),
        "project_id": str(rule.project_id),
        "wallet_id": str(rule.wallet_id),
        "network": rule.network.slug,
        "asset_id": str(rule.asset_id),
        "threshold_amount": str(int(rule.threshold_amount)),
        "enabled": rule.enabled,
        "trigger_count": rule.trigger_count,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


def _role(request, project: Project):
    membership = Membership.objects.filter(
        organization=project.organization, user=request.actor
    ).first()
    return membership.role if membership else None


def _endpoint_out(endpoint: SweepDestinationEndpoint) -> dict:
    return {
        "endpoint_url": endpoint.url,
        "url": endpoint.url,
        "enabled": endpoint.enabled,
        "version": endpoint.version,
        "has_signing_secret": bool(endpoint.signing_secret_ciphertext),
        "updated_by": str(endpoint.updated_by_id) if endpoint.updated_by_id else None,
        "updated_at": endpoint.updated_at.isoformat(),
    }


@dashboard_router.get(
    "/sweep-destination-endpoint", response={200: dict, 404: dict}
)
def get_endpoint(request, project_id: str):
    project = resolve_project(request, project_id)
    endpoint = services.get_endpoint(project)
    if endpoint is None:
        raise HttpError(404, "no sweep endpoint registered for this project")
    return _endpoint_out(endpoint)


@dashboard_router.put(
    "/sweep-destination-endpoint", response={200: dict, 403: dict, 404: dict, 422: dict}
)
def put_endpoint(request, payload: EndpointIn):
    project = resolve_project(request, payload.project_id)
    if _role(request, project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "endpoint registration requires an owner or administrator")
    url = payload.endpoint_url or payload.url or ""
    if not url:
        raise HttpError(422, "endpoint_url is required")
    try:
        endpoint = services.register_endpoint(
            project=project,
            url=url,
            actor=request.actor,
            enabled=payload.enabled,
            signing_secret=payload.signing_secret,
        )
    except resolver.ResolutionError as exc:
        raise HttpError(422, f"{exc.stage}: {exc.message}") from exc
    return _endpoint_out(endpoint)


@dashboard_router.delete(
    "/sweep-destination-endpoint", response={200: dict, 403: dict, 404: dict}
)
def delete_endpoint(request, project_id: str):
    project = resolve_project(request, project_id)
    if _role(request, project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "endpoint changes require an owner or administrator")
    endpoint = services.disable_endpoint(project=project, actor=request.actor)
    if endpoint is None:
        raise HttpError(404, "no sweep endpoint registered for this project")
    return _endpoint_out(endpoint)


@dashboard_router.get(
    "/sweep-destination-endpoint/history", response={200: list[dict], 404: dict}
)
def endpoint_history(request, project_id: str):
    project = resolve_project(request, project_id)
    endpoint = services.get_endpoint(project)
    if endpoint is None:
        raise HttpError(404, "no sweep endpoint registered for this project")
    return [
        {
            "action": row.action,
            "actor_id": row.actor_id,
            "previous_url_hash": row.previous_url_hash,
            "new_url_hash": row.new_url_hash,
            "created_at": row.created_at.isoformat(),
        }
        for row in endpoint.history.all()
    ]


@dashboard_router.post(
    "/sweep-destination-endpoint/test", response={200: dict, 404: dict, 422: dict}
)
def test_endpoint(request, payload: EndpointTestIn):
    project = resolve_project(request, payload.project_id)
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    asset = (
        Asset.objects.filter(id=payload.asset_id).first()
        if payload.asset_id
        else Asset.objects.filter(network=network, token_standard="native").first()
        if network
        else None
    )
    if network is None or asset is None:
        raise HttpError(422, "unknown network or asset")
    try:
        result = services.test_resolution(project=project, network=network, asset=asset)
    except resolver.ResolutionError as exc:
        return 422, {"stage": exc.stage, "detail": exc.message}
    return {"address": result.address, "normalized": result.normalized, "network": network.slug}


@dashboard_router.post(
    "/auto-sweep-rules", response={201: dict, 403: dict, 404: dict, 409: dict, 422: dict}
)
def create_auto_rule(request, payload: AutoRuleIn):
    wallet = Wallet.objects.filter(id=payload.wallet_id).select_related("project").first()
    if wallet is None:
        raise HttpError(404, "wallet not found")
    resolve_project(request, str(wallet.project_id))
    if _role(request, wallet.project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "auto-sweep rules require an owner or administrator")
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    asset = Asset.objects.filter(id=payload.asset_id).first()
    if network is None or asset is None or asset.network_id != network.id:
        raise HttpError(422, "unknown network or asset for that network")
    try:
        threshold = int(payload.threshold_amount)
    except ValueError as exc:
        raise HttpError(422, "threshold_amount must be an integer (base units)") from exc
    if threshold <= 0:
        raise HttpError(422, "threshold_amount must be positive")
    if AutoSweepRule.objects.filter(
        wallet=wallet, network=network, asset=asset
    ).exists():
        raise HttpError(409, "an auto-sweep rule already exists for this wallet/network/asset")
    rule = AutoSweepRule.objects.create(
        project=wallet.project, wallet=wallet, network=network, asset=asset,
        threshold_amount=threshold, enabled=payload.enabled, created_by=request.actor,
    )
    return 201, _auto_rule_out(rule)


@dashboard_router.get("/auto-sweep-rules", response={200: list[dict], 404: dict})
def list_auto_rules(request, project_id: str = ""):
    project = resolve_project(request, project_id or None)
    return [
        _auto_rule_out(rule)
        for rule in AutoSweepRule.objects.filter(project=project)
        .select_related("network")
        .order_by("created_at")
    ]


@dashboard_router.delete(
    "/auto-sweep-rules/{rule_id}", response={200: dict, 403: dict, 404: dict}
)
def delete_auto_rule(request, rule_id: str):
    rule = AutoSweepRule.objects.filter(id=rule_id).select_related("project").first()
    if rule is None:
        raise HttpError(404, "rule not found")
    resolve_project(request, str(rule.project_id))
    if _role(request, rule.project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "auto-sweep rules require an owner or administrator")
    rule.delete()
    return {"detail": "deleted"}


class SweepPolicyIn(Schema):
    project_id: str
    destination_mode: str = "resolver"
    min_sweep_threshold: str = "0"
    leave_behind: str = "0"
    enabled: bool = True


def _policy_out(policy: SweepPolicy) -> dict:
    return {
        "project_id": str(policy.project_id),
        "destination_mode": policy.destination_mode,
        "min_sweep_threshold": str(int(policy.min_sweep_threshold)),
        "leave_behind": str(int(policy.leave_behind)),
        "enabled": policy.enabled,
    }


@dashboard_router.get("/sweep-policy", response={200: dict, 404: dict})
def get_sweep_policy(request, project_id: str):
    project = resolve_project(request, project_id)
    policy = SweepPolicy.objects.filter(project=project).first()
    if policy is None:
        policy = SweepPolicy(project=project)
    return _policy_out(policy)


@dashboard_router.put(
    "/sweep-policy", response={200: dict, 403: dict, 404: dict, 422: dict}
)
def put_sweep_policy(request, payload: SweepPolicyIn):
    project = resolve_project(request, payload.project_id)
    if _role(request, project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "sweep policy requires an owner or administrator")
    if payload.destination_mode not in ("resolver", "static"):
        raise HttpError(422, "destination_mode must be 'resolver' or 'static'")
    try:
        threshold = int(payload.min_sweep_threshold)
        leave_behind = int(payload.leave_behind)
    except ValueError as exc:
        raise HttpError(422, "amounts must be integers (base units)") from exc
    if threshold < 0 or leave_behind < 0:
        raise HttpError(422, "amounts cannot be negative")
    policy, _ = SweepPolicy.objects.update_or_create(
        project=project,
        defaults={
            "destination_mode": payload.destination_mode,
            "min_sweep_threshold": threshold,
            "leave_behind": leave_behind,
            "enabled": payload.enabled,
        },
    )
    return _policy_out(policy)


class StaticDestinationIn(Schema):
    project_id: str
    network: str
    address: str
    label: str = ""


def _destination_out(destination: StaticSweepDestination) -> dict:
    return {
        "id": str(destination.id),
        "project_id": str(destination.project_id),
        "network": destination.network.slug,
        "address": destination.address,
        "label": destination.label,
        "enabled": destination.enabled,
    }


@dashboard_router.put(
    "/sweep-destinations", response={200: dict, 403: dict, 404: dict, 422: dict}
)
def put_static_destination(request, payload: StaticDestinationIn):
    project = resolve_project(request, payload.project_id)
    if _role(request, project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "static destinations require an owner or administrator")
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    if network is None:
        raise HttpError(422, "unknown network")
    try:
        destination = services.set_static_destination(
            project=project, network=network, address=payload.address,
            label=payload.label, actor=request.actor,
        )
    except services.SweepError as exc:
        raise HttpError(422, str(exc)) from exc
    return _destination_out(destination)


@dashboard_router.get("/sweep-destinations", response={200: list[dict], 404: dict})
def list_static_destinations(request, project_id: str):
    project = resolve_project(request, project_id)
    return [
        _destination_out(row)
        for row in StaticSweepDestination.objects.filter(project=project).select_related("network")
    ]


@dashboard_router.delete(
    "/sweep-destinations/{destination_id}", response={200: dict, 403: dict, 404: dict}
)
def delete_static_destination(request, destination_id: str):
    destination = (
        StaticSweepDestination.objects.filter(id=destination_id)
        .select_related("project")
        .first()
    )
    if destination is None:
        raise HttpError(404, "destination not found")
    resolve_project(request, str(destination.project_id))
    if _role(request, destination.project) not in services.ENDPOINT_ADMIN_ROLES:
        raise HttpError(403, "static destinations require an owner or administrator")
    destination.delete()
    return {"detail": "deleted"}


def _serialize_sweep(sweep: Sweep) -> dict:
    snapshot = getattr(sweep, "destination_snapshot", None)
    return {
        "id": str(sweep.id),
        "wallet_id": str(sweep.wallet_id),
        "network": sweep.network.slug,
        "asset": sweep.asset.symbol,
        "status": sweep.status,
        "status_reason": sweep.status_reason,
        "amount": str(int(sweep.amount)) if sweep.amount is not None else None,
        "destination_address": snapshot.destination_address if snapshot else None,
        "approvals_required": sweep.approvals_required,
        "approvals_received": sweep.approvals.filter(decision="approved").count(),
        "chain_tx_hash": sweep.chain_tx_hash,
        "external_reference": sweep.external_reference,
        "created_at": sweep.created_at.isoformat(),
    }


@router.post("/sweeps", response={201: dict, 403: dict, 404: dict, 422: dict})
def create_sweep(request, payload: dict = Body(...)):  # noqa: B008 - Ninja body marker
    keys = set(payload.keys())
    forbidden = keys & FORBIDDEN_DESTINATION_FIELDS
    if forbidden:
        raise HttpError(
            422,
            "destination_not_allowed: sweep destinations come only from the "
            "registered endpoint; remove "
            + ", ".join(sorted(forbidden)),
        )
    unknown = keys - ALLOWED_SWEEP_FIELDS
    if unknown:
        raise HttpError(422, f"unknown field(s): {', '.join(sorted(unknown))}")
    wallet = Wallet.objects.filter(id=payload.get("wallet_id")).select_related("project").first()
    if wallet is None:
        raise HttpError(404, "wallet not found")
    if is_machine(request):
        if str(request.api_key.project_id) != str(wallet.project_id):
            raise HttpError(404, "wallet not found")
        if not has_any_scope(request, "sweeps:write"):
            raise HttpError(403, "missing scope: sweeps:write")
        actor_type, actor_id = "api", str(request.api_key.id)
    else:
        resolve_project(request, str(wallet.project_id))
        if _role(request, wallet.project) not in services.SWEEP_REQUESTER_ROLES:
            raise HttpError(403, "your role cannot request sweeps")
        actor_type, actor_id = "dashboard", str(request.actor.id)
    network = BlockchainNetwork.objects.filter(slug=payload.get("network")).first()
    asset = Asset.objects.filter(id=payload.get("asset_id")).first()
    if network is None or asset is None:
        raise HttpError(422, "unknown network or asset")
    idempotency_key = request.headers.get("Idempotency-Key", "")
    if not idempotency_key:
        raise HttpError(422, "Idempotency-Key header is required")
    try:
        sweep = services.create_sweep(
            wallet=wallet,
            network=network,
            asset=asset,
            idempotency_key=idempotency_key,
            external_reference=payload.get("external_reference", ""),
            requested_by_type=actor_type,
            requested_by_id=actor_id,
        )
    except services.SweepError as exc:
        raise HttpError(422, str(exc)) from exc
    return 201, _serialize_sweep(sweep)


@router.get("/sweeps", response={200: list[dict], 403: dict, 404: dict, 422: dict})
def list_sweeps(request, project_id: str = ""):
    if is_machine(request):
        if not has_any_scope(request, "sweeps:read", "read"):
            raise HttpError(403, "missing scope: sweeps:read")
        project_ids = [request.api_key.project_id]
    else:
        project = resolve_project(request, project_id or None)
        project_ids = [project.id]
    queryset = (
        Sweep.objects.filter(project_id__in=project_ids)
        .select_related("network", "asset", "destination_snapshot")
        .order_by("-created_at")[:200]
    )
    return [_serialize_sweep(item) for item in queryset]


@router.get("/sweeps/{sweep_id}", response={200: dict, 404: dict})
def get_sweep(request, sweep_id: str):
    item = (
        Sweep.objects.filter(id=sweep_id)
        .select_related("network", "asset", "destination_snapshot")
        .first()
    )
    if item is None:
        raise HttpError(404, "sweep not found")
    if is_machine(request):
        if str(request.api_key.project_id) != str(item.project_id):
            raise HttpError(404, "sweep not found")
    else:
        resolve_project(request, str(item.project_id))
    return _serialize_sweep(item)


@dashboard_router.post(
    "/sweeps/{sweep_id}/approve", response={200: dict, 404: dict, 422: dict}
)
def approve_sweep(request, sweep_id: str, payload: ApprovalIn):
    return _decide(request, sweep_id, "approved", payload.note)


@dashboard_router.post(
    "/sweeps/{sweep_id}/reject", response={200: dict, 404: dict, 422: dict}
)
def reject_sweep(request, sweep_id: str, payload: ApprovalIn):
    return _decide(request, sweep_id, "rejected", payload.note)


def _decide(request, sweep_id: str, decision: str, note: str):
    item = Sweep.objects.filter(id=sweep_id).first()
    if item is None:
        raise HttpError(404, "sweep not found")
    resolve_project(request, str(item.project_id))
    try:
        updated = services.record_sweep_approval(
            sweep=item, approver=request.actor, decision=decision, note=note
        )
    except services.SweepError as exc:
        raise HttpError(422, str(exc)) from exc
    return _serialize_sweep(updated)
