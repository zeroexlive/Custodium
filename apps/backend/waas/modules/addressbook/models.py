"""Destination address book (withdrawal allowlist source).

A project keeps a book of vetted destination addresses. On its
own the book is informational; when the project's
``withdrawal_allowlist_required`` flag is on, withdrawal creation
refuses any destination that is not in the book for that network
(enforced in `waas.modules.operations.services` beside the
blacklist check). This is a tenant-controlled allowlist — the
opposite direction from the manual blacklist — and entries are
managed by organization owner/administrator roles only.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class DestinationAddress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="destination_addresses"
    )
    network = models.ForeignKey(
        "networks.BlockchainNetwork",
        on_delete=models.PROTECT,
        related_name="destination_addresses",
    )
    address = models.CharField(max_length=256)
    normalized_address = models.CharField(max_length=256, db_index=True)
    label = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_destination_addresses",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "addressbook_destination_address"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "network", "normalized_address"],
                name="uniq_destination_project_network_address",
            )
        ]

    def __str__(self) -> str:
        return f"DestinationAddress({self.network.slug}, {self.address})"
