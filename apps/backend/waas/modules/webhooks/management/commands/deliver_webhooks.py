"""Worker entrypoint: attempt every due webhook delivery."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from waas.modules.webhooks import services
from waas.modules.webhooks.models import WebhookDelivery


class Command(BaseCommand):
    help = "Attempt due webhook deliveries (retries per the delivery ladder)."

    def handle(self, *args, **options) -> None:
        due = WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.PENDING,
            next_attempt_at__lte=timezone.now(),
        ).select_related("event", "endpoint")[:500]
        attempted = 0
        for delivery in due:
            services.attempt_delivery(delivery)
            attempted += 1
        self.stdout.write(f"attempted={attempted}")
