"""Phase 11 webhooks: tenant-registered HTTPS endpoints, the
events emitted by the platform's lifecycle points, and signed
deliveries with bounded retries and replay.

Delivery contract (docs/api/webhooks.md): POST JSON with
`WaaS-Signature: t=<unix>,v1=<hmac-sha256 hex>` over
`f"{t}.{raw_body}"` using the endpoint's own secret (separate
from API HMAC keys), plus `X-WaaS-Event-Id` (idempotency) and
`X-WaaS-Event-Type` headers. 2xx = delivered; anything else
retries on a fixed backoff ladder and then goes dead.
"""

from __future__ import annotations

import uuid

from django.db import models

from waas.modules.projects.models import Project

EVENT_TYPES = [
    "deposit.credited",
    "withdrawal.completed",
    "withdrawal.failed",
    "sweep.completed",
    "sweep.failed",
]

# Seconds after the previous attempt: ~1m, 5m, 30m, 2h, 12h.
RETRY_DELAYS = [60, 300, 1800, 7200, 43200]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


class WebhookEndpoint(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    url = models.URLField(max_length=500)
    events = models.JSONField(default=list)  # subscribed event types; [] = none
    signing_secret_ciphertext = models.TextField()  # Fernet; shown once at creation
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="webhook_events"
    )
    event_type = models.CharField(max_length=48)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        DELIVERED = "delivered"
        DEAD = "dead"

    event = models.ForeignKey(
        WebhookEvent, on_delete=models.CASCADE, related_name="deliveries"
    )
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
