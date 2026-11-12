"""Seed the plan catalog (idempotent)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.plans.models import Plan

PLANS = [
    {
        "slug": "sandbox",
        "name": "Sandbox",
        "monthly_price_cents": 0,
        "quotas": {
            "max_wallets": 25,
            "max_api_keys_per_project": 10,
            "included_withdrawals_per_month": 100,
            "withdrawal_overage_cents": 25,
        },
    },
    {
        "slug": "growth",
        "name": "Growth",
        "monthly_price_cents": 49_900,
        "quotas": {
            "max_wallets": 250,
            "max_api_keys_per_project": 50,
            "included_withdrawals_per_month": 2_500,
            "withdrawal_overage_cents": 15,
        },
    },
    {
        "slug": "scale",
        "name": "Scale",
        "monthly_price_cents": 249_900,
        "quotas": {
            "max_wallets": 5_000,
            "max_api_keys_per_project": 250,
            "included_withdrawals_per_month": 25_000,
            "withdrawal_overage_cents": 8,
        },
    },
]


class Command(BaseCommand):
    help = "Seed the subscription plan catalog."

    def handle(self, *args, **options) -> None:
        for spec in PLANS:
            Plan.objects.update_or_create(slug=spec["slug"], defaults=spec)
        self.stdout.write(f"plans seeded: {len(PLANS)}")
