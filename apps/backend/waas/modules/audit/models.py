from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """Append-only security/operations audit trail. Never store secrets here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=100, db_index=True)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    api_key = models.ForeignKey(
        "api_credentials.ApiKey", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "audit_audit_event"
        ordering = ["-created_at"]

    @classmethod
    def record(cls, event_type: str, **kwargs: object) -> AuditEvent:
        return cls.objects.create(event_type=event_type, **kwargs)
