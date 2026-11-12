"""Blacklist matching: platform entries apply to everyone; tenant
entries apply only to their own organization (optionally one project).
Matching is on the per-chain normalised address form."""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from waas.common.address_normalization import family_for_slug, normalize_address
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Organization
from waas.modules.projects.models import Project


def find_matches(
    *,
    address: str,
    network: BlockchainNetwork,
    organization: Organization | None = None,
    project: Project | None = None,
) -> list[BlacklistEntry]:
    """Return effective entries matching this address for the tenant context.

    Raises ValueError if the address cannot be parsed for the network's
    chain family — an unparseable address is an error, never a silent miss.
    """
    normalized = normalize_address(family_for_slug(network.slug), address)
    now = timezone.now()
    query = Q(normalized_address=normalized, network=network, active=True) & (
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    scope = Q(scope=BlacklistEntry.Scope.PLATFORM, project__isnull=True)
    if organization is not None:
        tenant_scope = Q(scope=BlacklistEntry.Scope.TENANT, organization=organization)
        if project is not None:
            tenant_scope &= Q(project__isnull=True) | Q(project=project)
        else:
            tenant_scope &= Q(project__isnull=True)
        scope |= tenant_scope
    return list(BlacklistEntry.objects.filter(query & scope))


def is_blacklisted(
    *,
    address: str,
    network: BlockchainNetwork,
    organization: Organization | None = None,
    project: Project | None = None,
) -> bool:
    return bool(
        find_matches(address=address, network=network, organization=organization, project=project)
    )
