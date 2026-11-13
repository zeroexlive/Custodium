from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Project(models.Model):
    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=200)
    environment = models.CharField(max_length=16, choices=Environment.choices)
    # When true, withdrawal creation refuses destinations that are
    # not in the project's destination address book (addressbook
    # module). Default off: the book is then purely informational.
    withdrawal_allowlist_required = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_projects"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_project"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name", "environment"], name="uniq_project_org_name_env"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.environment})"
