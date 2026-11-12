from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


class Organization(models.Model):
    """Tenant root. Every tenant-owned resource traces back to an Organization."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    is_suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations_organization"

    def __str__(self) -> str:
        return self.name

    @classmethod
    def create_with_owner(cls, name: str, owner: object) -> Organization:
        base = slugify_name(name)
        slug = base
        counter = 2
        while cls.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        org = cls.objects.create(name=name, slug=slug)
        Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
        return org


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMINISTRATOR = "administrator", "Administrator"
        DEVELOPER = "developer", "Developer"
        FINANCE_OPERATOR = "finance_operator", "Finance Operator"
        WITHDRAWAL_APPROVER = "withdrawal_approver", "Withdrawal Approver"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "organizations_membership"
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="uniq_membership_org_user")
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"
