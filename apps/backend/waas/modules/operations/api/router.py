"""Phase 9 financial-operations API: withdrawal requests,
approvals, policy management, and the finance export.

Tenant context always comes from the authenticated identity
(machine key → its project; dashboard user → membership), never
from the request body (Phase 1 discipline). Dispatch itself is
worker-driven (`process_withdrawals`), not API-triggered.
"""

from __future__ import annotations

from django.http import HttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.modules.assets.models import Asset
from waas.modules.audit.models import AuditEvent
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

from .. import services
from ..models import WithdrawalPolicy, WithdrawalRequest

router = Router(tags=["operations"], auth=AnyAuth())
dashboard_router = Router(tags=["operations-dashboard"], auth=DashboardAuth())


class WithdrawalCreateIn(Schema):
    wallet_id: str
    network: str
    asset_id: str
    destination_address: str
    amount: str  # integer base units, as a string
    external_reference: str = ""
    project_id: str = ""  # dashboard callers only; ignored for machine keys


class ApprovalIn(Schema):
    note: str = ""


class RefundIn(Schema):
    amount: str
    reason: str


class PolicyIn(Schema):
    asset_id: str | None = None
    max_single_amount: str | None = None
    daily_limit: str | None = None
    approvals_required: int = 1
    auto_approve_below: str = "0"
    service_fee_flat: str = "0"


def _serialize(request_obj: WithdrawalRequest) -> dict:
    return {
        "id": str(request_obj.id),
        "wallet_id": str(request_obj.wallet_id),
        "network": request_obj.network.slug,
        "asset": request_obj.asset.symbol,
        "destination_address": request_obj.destination_address,
        "amount": str(int(request_obj.amount)),
        "status": request_obj.status,
        "status_reason": request_obj.status_reason,
        "external_reference": request_obj.external_reference,
        "approvals_required": request_obj.approvals_required,
        "approvals_received": request_obj.approvals.filter(decision="approved").count(),
        "service_fee": str(int(request_obj.service_fee)),
        "actual_fee": (
            str(int(request_obj.actual_fee)) if request_obj.actual_fee is not None else None
        ),
        "fee_asset": request_obj.fee_asset.symbol if request_obj.fee_asset else None,
        "chain_tx_hash": request_obj.chain_tx_hash,
        "refunded_amount": str(int(request_obj.refunded_amount)),
        "created_at": request_obj.created_at.isoformat(),
    }


def _parse_amount(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HttpError(422, "amount must be an integer string in base units") from None
    if value <= 0:
        raise HttpError(422, "amount must be positive")
    return value


def _membership_role(request, project: Project):
    membership = Membership.objects.filter(
        organization=project.organization, user=request.actor
    ).first()
    return membership.role if membership else None


@router.post("/withdrawals", response={201: dict, 404: dict, 422: dict, 403: dict})
def create_withdrawal(request, payload: WithdrawalCreateIn):
    wallet = Wallet.objects.filter(id=payload.wallet_id).select_related("project").first()
    if wallet is None:
        raise HttpError(404, "wallet not found")
    if is_machine(request):
        api_key = request.api_key
        if str(api_key.project_id) != str(wallet.project_id):
            raise HttpError(404, "wallet not found")
        if not has_any_scope(request, "withdrawals:write"):
            raise HttpError(403, "missing scope: withdrawals:write")
        actor_type, actor_id = "api", str(api_key.id)
    else:
        resolve_project(request, str(wallet.project_id))
        role = _membership_role(request, wallet.project)
        if role not in services.REQUESTER_ROLES:
            raise HttpError(403, "your role cannot request withdrawals")
        actor_type, actor_id = "dashboard", str(request.actor.id)
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    asset = Asset.objects.filter(id=payload.asset_id).first()
    if network is None or asset is None:
        raise HttpError(422, "unknown network or asset")
    idempotency_key = request.headers.get("Idempotency-Key", "")
    if not idempotency_key:
        raise HttpError(422, "Idempotency-Key header is required")
    try:
        created = services.create_withdrawal_request(
            wallet=wallet,
            network=network,
            asset=asset,
            destination_address=payload.destination_address,
            amount=_parse_amount(payload.amount),
            idempotency_key=idempotency_key,
            external_reference=payload.external_reference,
            requested_by_type=actor_type,
            requested_by_id=actor_id,
        )
    except services.OperationsError as exc:
        raise HttpError(422, str(exc)) from exc
    return 201, _serialize(created)


@router.get("/withdrawals", response={200: list[dict], 403: dict, 404: dict})
def list_withdrawals(request, project_id: str = "", status: str = ""):
    if is_machine(request):
        if not has_any_scope(request, "withdrawals:read", "transactions:read", "read"):
            raise HttpError(403, "missing scope: withdrawals:read")
        project_ids = [request.api_key.project_id]
    else:
        project = resolve_project(request, project_id or None)
        project_ids = [project.id]
    queryset = WithdrawalRequest.objects.filter(project_id__in=project_ids).select_related(
        "network", "asset", "fee_asset"
    )
    if status:
        queryset = queryset.filter(status=status)
    return [_serialize(item) for item in queryset.order_by("-created_at")[:200]]


@router.get("/withdrawals/{request_id}", response={200: dict, 404: dict})
def get_withdrawal(request, request_id: str):
    item = (
        WithdrawalRequest.objects.filter(id=request_id)
        .select_related("network", "asset", "fee_asset")
        .first()
    )
    if item is None:
        raise HttpError(404, "withdrawal not found")
    if is_machine(request):
        if str(request.api_key.project_id) != str(item.project_id):
            raise HttpError(404, "withdrawal not found")
    else:
        resolve_project(request, str(item.project_id))
    return _serialize(item)


@dashboard_router.post(
    "/withdrawals/{request_id}/approve", response={200: dict, 403: dict, 404: dict, 422: dict}
)
def approve_withdrawal(request, request_id: str, payload: ApprovalIn):
    return _decide(request, request_id, "approved", payload.note)


@dashboard_router.post(
    "/withdrawals/{request_id}/reject", response={200: dict, 403: dict, 404: dict, 422: dict}
)
def reject_withdrawal(request, request_id: str, payload: ApprovalIn):
    return _decide(request, request_id, "rejected", payload.note)


def _decide(request, request_id: str, decision: str, note: str):
    item = WithdrawalRequest.objects.filter(id=request_id).first()
    if item is None:
        raise HttpError(404, "withdrawal not found")
    resolve_project(request, str(item.project_id))
    try:
        updated = services.record_approval(
            request=item, approver=request.actor, decision=decision, note=note
        )
    except services.OperationsError as exc:
        raise HttpError(422, str(exc)) from exc
    return _serialize(updated)


@dashboard_router.post(
    "/withdrawals/{request_id}/refund", response={200: dict, 403: dict, 404: dict, 422: dict}
)
def refund_withdrawal(request, request_id: str, payload: RefundIn):
    item = WithdrawalRequest.objects.filter(id=request_id).first()
    if item is None:
        raise HttpError(404, "withdrawal not found")
    resolve_project(request, str(item.project_id))
    role = _membership_role(request, item.project)
    if role not in (Membership.Role.OWNER, Membership.Role.ADMINISTRATOR):
        raise HttpError(403, "refunds require an owner or administrator")
    try:
        updated = services.record_refund(
            request=item,
            amount=_parse_amount(payload.amount),
            actor=request.actor,
            reason=payload.reason,
        )
    except services.OperationsError as exc:
        raise HttpError(422, str(exc)) from exc
    return _serialize(updated)


@dashboard_router.get(
    "/projects/{project_id}/withdrawal-policy", response={200: dict, 404: dict}
)
def get_policy(request, project_id: str, asset_id: str | None = None):
    project = resolve_project(request, project_id)
    asset = Asset.objects.filter(id=asset_id).first() if asset_id else None
    policy = services.resolve_policy(project=project, asset=asset) if asset else (
        WithdrawalPolicy.objects.filter(project=project, asset__isnull=True).first()
        or WithdrawalPolicy(project=project)
    )
    return {
        "approvals_required": policy.approvals_required,
        "max_single_amount": (
            str(int(policy.max_single_amount)) if policy.max_single_amount is not None else None
        ),
        "daily_limit": str(int(policy.daily_limit)) if policy.daily_limit is not None else None,
        "auto_approve_below": str(int(policy.auto_approve_below)),
        "service_fee_flat": str(int(policy.service_fee_flat)),
    }


@dashboard_router.put(
    "/projects/{project_id}/withdrawal-policy", response={200: dict, 403: dict, 404: dict}
)
def put_policy(request, project_id: str, payload: PolicyIn):
    project = resolve_project(request, project_id)
    role = _membership_role(request, project)
    if role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMINISTRATOR,
        Membership.Role.FINANCE_OPERATOR,
    ):
        raise HttpError(403, "your role cannot edit withdrawal policy")
    asset = Asset.objects.filter(id=payload.asset_id).first() if payload.asset_id else None
    policy, _ = WithdrawalPolicy.objects.update_or_create(
        project=project,
        asset=asset,
        defaults={
            "max_single_amount": (
                int(payload.max_single_amount) if payload.max_single_amount else None
            ),
            "daily_limit": int(payload.daily_limit) if payload.daily_limit else None,
            "approvals_required": payload.approvals_required,
            "auto_approve_below": int(payload.auto_approve_below or 0),
            "service_fee_flat": int(payload.service_fee_flat or 0),
        },
    )
    return {
        "approvals_required": policy.approvals_required,
        "max_single_amount": (
            str(int(policy.max_single_amount)) if policy.max_single_amount is not None else None
        ),
        "daily_limit": str(int(policy.daily_limit)) if policy.daily_limit is not None else None,
        "auto_approve_below": str(int(policy.auto_approve_below)),
        "service_fee_flat": str(int(policy.service_fee_flat)),
    }


@dashboard_router.get("/projects/{project_id}/finance/journal-export")
def journal_export(request, project_id: str, days: int = 30):
    project = resolve_project(request, project_id)
    role = _membership_role(request, project)
    if role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMINISTRATOR,
        Membership.Role.FINANCE_OPERATOR,
    ):
        raise HttpError(403, "your role cannot export finance data")
    content = services.export_journal_csv(project=project, days=days)
    response = HttpResponse(content, content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="journal-{project_id}.csv"'
    )
    return response


# ------------------------------------------------------- operator controls
operator_router = Router(tags=["operator"], auth=DashboardAuth())


class HaltIn(Schema):
    active: bool
    reason: str = ""


@operator_router.get("/operator/platform-halt", response={200: dict, 403: dict})
def get_platform_halt(request):
    if not getattr(request.actor, "is_staff", False):
        raise HttpError(403, "platform halt is an operator control")
    from waas.modules.operations.models import PlatformHalt

    row = PlatformHalt.objects.filter(pk=1).first()
    return {
        "active": bool(row and row.active),
        "reason": row.reason if row else "",
        "updated_at": row.updated_at.isoformat() if row else None,
    }


@operator_router.post("/operator/platform-halt", response={200: dict, 403: dict})
def set_platform_halt(request, payload: HaltIn):
    """Phase 12 kill switch: staff-only, reason required to
    activate, every change audited."""
    if not getattr(request.actor, "is_staff", False):
        raise HttpError(403, "platform halt is an operator control")
    if payload.active and not payload.reason.strip():
        raise HttpError(422, "a reason is required to activate the platform halt")
    from waas.modules.operations.models import PlatformHalt

    row, _ = PlatformHalt.objects.get_or_create(pk=1)
    row.active = payload.active
    row.reason = payload.reason.strip()[:500]
    row.save(update_fields=["active", "reason", "updated_at"])
    AuditEvent.record(
        "operator.platform_halt_changed",
        actor_user=request.actor,
        metadata={"active": payload.active, "reason": row.reason},
    )
    return {"active": row.active, "reason": row.reason}
