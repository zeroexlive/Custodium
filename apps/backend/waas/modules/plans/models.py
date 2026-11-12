"""Phase 11 commercial layer: plans with quotas, per-organisation
subscriptions, and fiat invoicing.

Billing is FIAT ONLY: invoices are computed from the plan price
plus metered overage and are payable off-platform; payment
collection is not integrated (no card data ever touches this
system), and invoice status transitions are explicit operator
actions. The custody ledger remains the crypto system of
record — nothing here moves crypto.
"""

from __future__ import annotations

from django.db import models

from waas.modules.organizations.models import Organization

DEFAULT_QUOTAS = {
    "max_wallets": 25,
    "max_api_keys_per_project": 10,
    "included_withdrawals_per_month": 100,
    "withdrawal_overage_cents": 25,
}


class Plan(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    monthly_price_cents = models.PositiveIntegerField(default=0)
    quotas = models.JSONField(default=dict)  # see DEFAULT_QUOTAS keys
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def quota(self, key: str) -> int:
        return int((self.quotas or {}).get(key, DEFAULT_QUOTAS[key]))


class OrganizationSubscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        PAST_DUE = "past_due"
        CANCELLED = "cancelled"

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        ISSUED = "issued"
        PAID = "paid"
        VOID = "void"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoices"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    line_items = models.JSONField(default=list)  # [{label, quantity, unit_cents, amount_cents}]
    total_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "period_start"],
                name="invoice_one_per_org_period",
            )
        ]
