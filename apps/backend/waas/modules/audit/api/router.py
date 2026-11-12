from __future__ import annotations

from ninja import Router

from waas.api.authentication import DashboardAuth
from waas.common.pagination import paginated
from waas.modules.audit.models import AuditEvent
from waas.modules.organizations.models import Membership

router = Router(tags=["audit"])
dashboard_auth = DashboardAuth()


@router.get("/audit-logs", response=dict, auth=dashboard_auth)
def list_audit_logs(request):
    org_ids = Membership.objects.filter(user=request.auth).values_list("organization_id", flat=True)
    events = AuditEvent.objects.filter(organization_id__in=list(org_ids))[:100]
    return paginated(
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "organization_id": str(e.organization_id) if e.organization_id else None,
            "project_id": str(e.project_id) if e.project_id else None,
            "metadata": e.metadata,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    )


@router.get("/audit-logs/export", auth=dashboard_auth)
def export_audit_logs(request):
    """Phase 11: audit export (CSV) for the caller's
    organisations — compliance/reporting surface."""
    import csv
    import io

    from django.http import HttpResponse

    org_ids = Membership.objects.filter(user=request.auth).values_list(
        "organization_id", flat=True
    )
    events = AuditEvent.objects.filter(organization_id__in=list(org_ids)).order_by(
        "created_at"
    )[:10_000]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["id", "created_at", "event_type", "organization_id", "project_id",
         "actor_user_id", "api_key_id", "metadata"]
    )
    for event in events:
        writer.writerow(
            [
                str(event.id), event.created_at.isoformat(), event.event_type,
                str(event.organization_id or ""), str(event.project_id or ""),
                str(event.actor_user_id or ""), str(event.api_key_id or ""),
                event.metadata,
            ]
        )
    response = HttpResponse(out.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="audit-log.csv"'
    return response


@router.get("/support/lookup", response={200: dict, 403: dict}, auth=dashboard_auth)
def support_lookup(request, q: str = ""):
    """Phase 11 support tooling: least-privilege, READ-ONLY,
    staff-only cross-tenant lookup. Every call is itself
    audit-logged (including the query) so support access is
    fully accountable. Returns identifiers and statuses only —
    never secrets, never balances beyond counts."""
    user = request.actor
    if not getattr(user, "is_staff", False):
        from ninja.errors import HttpError

        raise HttpError(403, "support lookup requires a staff account")
    from django.contrib.auth import get_user_model

    from waas.modules.operations.models import WithdrawalRequest
    from waas.modules.organizations.models import Organization
    from waas.modules.sweeps.models import Sweep
    from waas.modules.wallets.models import Wallet

    AuditEvent.record(
        "support.lookup", actor_user=user, metadata={"query": q[:200]}
    )
    needle = q.strip()
    result: dict = {"query": needle}
    if not needle:
        return result
    account = get_user_model().objects.filter(email__iexact=needle).first()
    if account is not None:
        result["user"] = {
            "id": str(account.id), "email": account.email,
            "organizations": [
                {"id": str(m.organization_id), "role": m.role}
                for m in Membership.objects.filter(user=account)
            ],
        }
    wallet = Wallet.objects.filter(id=needle).select_related("project").first() if _is_uuid(needle) else None
    if wallet is not None:
        result["wallet"] = {
            "id": str(wallet.id), "label": wallet.label,
            "project_id": str(wallet.project_id), "status": wallet.status,
        }
    withdrawal = (
        WithdrawalRequest.objects.filter(id=needle).first() if _is_uuid(needle) else None
    )
    if withdrawal is not None:
        result["withdrawal"] = {
            "id": str(withdrawal.id), "status": withdrawal.status,
            "network": withdrawal.network.slug, "asset": withdrawal.asset.symbol,
            "amount": str(int(withdrawal.amount)),
        }
    sweep = Sweep.objects.filter(id=needle).first() if _is_uuid(needle) else None
    if sweep is not None:
        result["sweep"] = {
            "id": str(sweep.id), "status": sweep.status,
            "network": sweep.network.slug, "asset": sweep.asset.symbol,
        }
    organization = Organization.objects.filter(id=needle).first() if _is_uuid(needle) else None
    if organization is not None:
        result["organization"] = {"id": str(organization.id), "name": organization.name}
    return result


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
