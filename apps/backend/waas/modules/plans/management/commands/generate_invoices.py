"""Generate the current period's invoices for all
organisations (idempotent per org+period)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.organizations.models import Organization
from waas.modules.plans import services


class Command(BaseCommand):
    help = "Generate current-period invoices for all organisations."

    def handle(self, *args, **options) -> None:
        count = 0
        for organization in Organization.objects.all():
            services.generate_invoice(organization)
            count += 1
        self.stdout.write(f"organisations invoiced: {count}")
