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
