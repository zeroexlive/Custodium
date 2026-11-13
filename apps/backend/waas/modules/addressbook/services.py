"""Address-book lookups used by withdrawal creation."""
from __future__ import annotations

from waas.common.address_normalization import family_for_slug, normalize_address
from waas.modules.addressbook.models import DestinationAddress


def is_allowlisted(*, project, network, address: str) -> bool:
    """True when `address` is in the project's book for `network`.

    Matching is on the family's normalized form, so case/format
    variants of the same address match the entry. An address that
    cannot be parsed for the family is simply not allowlisted.
    """
    try:
        normalized = normalize_address(family_for_slug(network.slug), address)
    except ValueError:
        return False
    return DestinationAddress.objects.filter(
        project=project, network=network, normalized_address=normalized
    ).exists()
