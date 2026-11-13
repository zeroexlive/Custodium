"""Webhook emission, delivery, and replay.

Emission is best-effort by design: it happens inside the
caller's transaction (so an event exists iff the state change
committed) but never raises into money-moving code paths.
Delivery runs from the `deliver_webhooks` worker command with
the same SSRF validation as the sweep resolver (HTTPS + public
IPs), signatures per the webhook contract, and the retry ladder
from the model. Endpoints are re-validated at every delivery —
a URL edited to point inward fails closed at delivery time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta

import httpx
from django.db import transaction
from django.utils import timezone

from waas.common.http_pinning import pinned_httpx_client
from waas.modules.projects.models import Project
from waas.modules.sweeps.resolver import (
    ResolutionError,
    validate_endpoint_url,
    validated_host_ips,
)
from waas.security.secret_management.crypto import decrypt_secret, encrypt_secret

from .models import (
    MAX_ATTEMPTS,
    RETRY_DELAYS,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)


def generate_signing_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def create_endpoint(
    *,
    project: Project,
    url: str,
    events: list[str],
    enabled: bool = True,
    dns_resolver=None,
) -> tuple[WebhookEndpoint, str]:
    """Validate (SSRF) and store a new endpoint; returns the row
    and the plaintext signing secret (shown exactly once)."""
    validate_kwargs = {}
    if dns_resolver is not None:
        validate_kwargs["dns_resolver"] = dns_resolver
    validate_endpoint_url(url, **validate_kwargs)
    secret = generate_signing_secret()
    endpoint = WebhookEndpoint.objects.create(
        project=project,
        url=url,
        events=events,
        signing_secret_ciphertext=encrypt_secret(secret),
        enabled=enabled,
    )
    return endpoint, secret


def rotate_signing_secret(*, endpoint: WebhookEndpoint) -> str:
    """Replace an endpoint's signing secret; returns the new
    plaintext (shown exactly once). Deliveries attempted after
    the rotation sign with the new secret; the old secret stops
    working immediately — receivers must be updated in step."""
    secret = generate_signing_secret()
    endpoint.signing_secret_ciphertext = encrypt_secret(secret)
    endpoint.save(update_fields=["signing_secret_ciphertext", "updated_at"])
    return secret


def emit_event(*, project: Project, event_type: str, data: dict) -> WebhookEvent | None:
    """Create an event + pending deliveries for subscribed,
    enabled endpoints. Returns None when nobody subscribes (the
    common case pre-Phase 11 configuration)."""
    endpoints = [
        endpoint
        for endpoint in WebhookEndpoint.objects.filter(project=project, enabled=True)
        if event_type in (endpoint.events or [])
    ]
    if not endpoints:
        return None
    event = WebhookEvent.objects.create(
        project=project, event_type=event_type, payload=data
    )
    for endpoint in endpoints:
        WebhookDelivery.objects.create(
            event=event, endpoint=endpoint, next_attempt_at=timezone.now()
        )
    return event


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()


def render_body(event: WebhookEvent) -> bytes:
    return json.dumps(
        {
            "id": str(event.id),
            "type": event.event_type,
            "created_at": event.created_at.isoformat(),
            "data": event.payload,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


@transaction.atomic
def attempt_delivery(
    delivery: WebhookDelivery, *, http_client: httpx.Client | None = None, dns_resolver=None
) -> WebhookDelivery:
    """One delivery attempt with full bookkeeping."""
    endpoint = delivery.endpoint
    now = timezone.now()
    delivery.attempts += 1
    try:
        validate_kwargs = {}
        if dns_resolver is not None:
            validate_kwargs["dns_resolver"] = dns_resolver
        wh_host, wh_ips = validated_host_ips(endpoint.url, **validate_kwargs)
    except ResolutionError as exc:
        delivery.last_error = f"endpoint validation failed: {exc.stage}: {exc.message}"
        return _schedule_retry(delivery, now)
    secret = decrypt_secret(endpoint.signing_secret_ciphertext)
    body = render_body(delivery.event)
    timestamp = int(now.timestamp())
    headers = {
        "Content-Type": "application/json",
        "X-WaaS-Event-Id": str(delivery.event.id),
        "X-WaaS-Event-Type": delivery.event.event_type,
        "WaaS-Signature": f"t={timestamp},v1={sign(secret, timestamp, body)}",
    }
    # Pin the socket to the validated IP (DNS-rebinding defence).
    client = http_client or pinned_httpx_client(
        host=wh_host, ip=wh_ips[0], timeout=httpx.Timeout(10.0, connect=3.0)
    )
    try:
        response = client.post(endpoint.url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        delivery.last_error = f"transport: {exc}"[:500]
        return _schedule_retry(delivery, now)
    delivery.last_status_code = response.status_code
    if 200 <= response.status_code < 300:
        delivery.status = WebhookDelivery.Status.DELIVERED
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        delivery.last_error = ""
    else:
        delivery.last_error = f"HTTP {response.status_code}"
        return _schedule_retry(delivery, now)
    delivery.save()
    return delivery


def _schedule_retry(delivery: WebhookDelivery, now) -> WebhookDelivery:
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = WebhookDelivery.Status.DEAD
        delivery.next_attempt_at = None
    else:
        delay = RETRY_DELAYS[delivery.attempts - 1]
        delivery.next_attempt_at = now + timedelta(seconds=delay)
    delivery.save()
    return delivery


def replay_delivery(delivery: WebhookDelivery) -> WebhookDelivery:
    """Operator/tenant replay: a dead or delivered delivery goes
    back to pending with its attempt counter reset."""
    delivery.status = WebhookDelivery.Status.PENDING
    delivery.attempts = 0
    delivery.next_attempt_at = timezone.now()
    delivery.last_error = ""
    delivery.save()
    return delivery
