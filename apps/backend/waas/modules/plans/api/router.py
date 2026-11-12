"""Phase 11 billing API (dashboard): plans, the caller's
subscription + usage, and invoices. Fiat only."""

from __future__ import annotations

from ninja import Router, Schema
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth
from waas.modules.organizations.models import Membership, Organization

from .. import services
from ..models import Invoice, OrganizationSubscription, Plan

router = Router(tags=["billing"], auth=DashboardAuth())


class SubscribeIn(Schema):
    plan_slug: str


def _org(request, organization_id: str) -> tuple[Organization, Membership]:
    organization = Organization.objects.filter(id=organization_id).first()
    membership = (
        Membership.objects.filter(organization=organization, user=request.actor).first()
        if organization
        else None
    )
    if organization is None or membership is None:
        raise HttpError(404, "organization not found")
    return organization, membership


@router.get("/plans", response={200: list[dict]})
def list_plans(request):
    return [
        {
            "slug": plan.slug,
            "name": plan.name,
            "monthly_price_cents": plan.monthly_price_cents,
            "quotas": plan.quotas,
        }
        for plan in Plan.objects.filter(active=True).order_by("monthly_price_cents")
    ]


@router.get("/organizations/{organization_id}/usage", response={200: dict, 404: dict})
def get_usage(request, organization_id: str):
    organization, _ = _org(request, organization_id)
    return services.usage_snapshot(organization)


@router.post(
    "/organizations/{organization_id}/subscription",
    response={200: dict, 403: dict, 404: dict},
)
def set_subscription(request, organization_id: str, payload: SubscribeIn):
    organization, membership = _org(request, organization_id)
    if membership.role not in (Membership.Role.OWNER, Membership.Role.ADMINISTRATOR):
        raise HttpError(403, "plan changes require an owner or administrator")
    plan = Plan.objects.filter(slug=payload.plan_slug, active=True).first()
    if plan is None:
        raise HttpError(404, "plan not found")
    subscription, _ = OrganizationSubscription.objects.update_or_create(
        organization=organization, defaults={"plan": plan, "status": "active"}
    )
    return {"organization_id": str(organization.id), "plan": plan.slug, "status": subscription.status}


@router.get("/organizations/{organization_id}/invoices", response={200: list[dict], 404: dict})
def list_invoices(request, organization_id: str):
    organization, _ = _org(request, organization_id)
    return [
        {
            "id": str(invoice.id),
            "period_start": invoice.period_start.isoformat(),
            "period_end": invoice.period_end.isoformat(),
            "line_items": invoice.line_items,
            "total_cents": invoice.total_cents,
            "currency": invoice.currency,
            "status": invoice.status,
        }
        for invoice in Invoice.objects.filter(organization=organization)
    ]


@router.post(
    "/invoices/{invoice_id}/mark-paid", response={200: dict, 403: dict, 404: dict}
)
def mark_invoice_paid(request, invoice_id: str):
    """Manual payment confirmation (collection happens
    off-platform; this records that it happened)."""
    invoice = Invoice.objects.filter(id=invoice_id).select_related("organization").first()
    if invoice is None:
        raise HttpError(404, "invoice not found")
    _, membership = _org(request, str(invoice.organization_id))
    if membership.role not in (Membership.Role.OWNER, Membership.Role.ADMINISTRATOR):
        raise HttpError(403, "only an owner or administrator can mark invoices paid")
    invoice.status = Invoice.Status.PAID
    invoice.save(update_fields=["status"])
    return {"id": str(invoice.id), "status": invoice.status}
