"""Plan/usage services: subscription resolution (defaulting to
the free Sandbox plan), current-period metering from the
operational tables, quota checks, and invoice generation."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from waas.modules.api_credentials.models import ApiKey
from waas.modules.operations.models import WithdrawalRequest
from waas.modules.organizations.models import Organization
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

from .models import Invoice, OrganizationSubscription, Plan


class QuotaExceeded(Exception):
    def __init__(self, resource: str, limit: int) -> None:
        super().__init__(f"plan quota exceeded: {resource} (limit {limit})")
        self.resource = resource
        self.limit = limit


def get_plan(organization: Organization) -> Plan:
    """The organisation's plan; organisations without a
    subscription row run on the default Sandbox plan."""
    subscription = (
        OrganizationSubscription.objects.filter(organization=organization)
        .select_related("plan")
        .first()
    )
    if subscription is not None:
        return subscription.plan
    plan = Plan.objects.filter(slug="sandbox").first()
    if plan is None:  # pragma: no cover - seed creates it; defensive default
        plan = Plan.objects.create(
            slug="sandbox", name="Sandbox", monthly_price_cents=0, quotas={}
        )
    return plan


def period_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or timezone.now().date()
    start = today.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def usage_snapshot(organization: Organization) -> dict:
    """Current-period usage, metered from the operational
    tables (no separate metering store to drift)."""
    projects = Project.objects.filter(organization=organization)
    start, end = period_bounds()
    wallets = Wallet.objects.filter(project__in=projects).count()
    withdrawals = WithdrawalRequest.objects.filter(
        project__in=projects,
        created_at__date__gte=start,
        created_at__date__lt=end,
    ).exclude(
        status__in=[
            WithdrawalRequest.Status.REJECTED,
            WithdrawalRequest.Status.FAILED,
        ]
    ).count()
    api_keys = ApiKey.objects.filter(project__in=projects, revoked_at__isnull=True).count()
    plan = get_plan(organization)
    return {
        "plan": plan.slug,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "wallets": {"used": wallets, "limit": plan.quota("max_wallets")},
        "api_keys": {"used": api_keys, "limit": plan.quota("max_api_keys_per_project")},
        "withdrawals_this_period": {
            "used": withdrawals,
            "included": plan.quota("included_withdrawals_per_month"),
        },
    }


def check_wallet_quota(project: Project) -> None:
    plan = get_plan(project.organization)
    used = Wallet.objects.filter(project__organization=project.organization).count()
    if used >= plan.quota("max_wallets"):
        raise QuotaExceeded("wallets", plan.quota("max_wallets"))


def check_api_key_quota(project: Project) -> None:
    plan = get_plan(project.organization)
    used = ApiKey.objects.filter(project=project, revoked_at__isnull=True).count()
    if used >= plan.quota("max_api_keys_per_project"):
        raise QuotaExceeded("api_keys", plan.quota("max_api_keys_per_project"))


@transaction.atomic
def generate_invoice(organization: Organization, *, today: date | None = None) -> Invoice:
    """One invoice per organisation per period (idempotent):
    plan price + withdrawal overage beyond the included count."""
    start, end = period_bounds(today)
    existing = Invoice.objects.filter(
        organization=organization, period_start=start
    ).first()
    if existing is not None:
        return existing
    plan = get_plan(organization)
    usage = usage_snapshot(organization)
    items = [
        {
            "label": f"{plan.name} plan (monthly)",
            "quantity": 1,
            "unit_cents": plan.monthly_price_cents,
            "amount_cents": plan.monthly_price_cents,
        }
    ]
    overage = max(
        0,
        usage["withdrawals_this_period"]["used"]
        - usage["withdrawals_this_period"]["included"],
    )
    if overage:
        unit = plan.quota("withdrawal_overage_cents")
        items.append(
            {
                "label": "Withdrawal overage",
                "quantity": overage,
                "unit_cents": unit,
                "amount_cents": overage * unit,
            }
        )
    return Invoice.objects.create(
        organization=organization,
        period_start=start,
        period_end=end,
        line_items=items,
        total_cents=sum(item["amount_cents"] for item in items),
        status=Invoice.Status.ISSUED,
    )
