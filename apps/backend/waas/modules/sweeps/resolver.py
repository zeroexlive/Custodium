"""The sweep destination resolver client (sweep-resolver.md
§§5–6, ADR 0006). Security properties, all fail-closed:

- HTTPS only; no credentials/fragment in the URL.
- Every DNS answer for the host must be a public IP (private,
  loopback, link-local, multicast, reserved, unspecified —
  including cloud metadata addresses — refuse the call).
  Hostnames that are IP literals are checked identically.
- No redirects: a 3xx is a resolution failure.
- Response must be 200, ≤ 512 bytes, and EXACTLY one plain-text
  address token (JSON, lists, commentary: rejected).
- The address must validate for the requested network.
- Bounded retries (2 attempts) for transport failures only;
  validation failures are never retried. No caching, no
  fallback, no last-known-good: a failed resolution is final.

DNS and transport are injectable so the SSRF/format matrix is
testable offline; production uses real DNS + httpx with TLS
verification (never disabled).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from waas.common.http_pinning import pinned_httpx_client

RESOLVER_VERSION = 1
MAX_BODY_BYTES = 512
CONNECT_TIMEOUT = 3.0
TOTAL_TIMEOUT = 5.0
MAX_ATTEMPTS = 2


class ResolutionError(Exception):
    """A resolution failure with its stage — the sweep fails
    closed with this recorded; there is no fallback."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class ResolvedDestination:
    address: str  # exactly as returned (trimmed)
    normalized: str  # network-canonical form used for signing/comparison
    raw_body_sha256: str


def _is_public_ip(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified


def default_dns_resolver(hostname: str) -> list[str]:
    infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def validated_host_ips(
    url: str, *, dns_resolver=default_dns_resolver
) -> tuple[str, list[str]]:
    """Validate an endpoint URL (§6) and return ``(host, ips)`` —
    every DNS answer must be a public IP. Callers that go on to
    connect MUST pin the socket to one of the returned IPs (see
    waas.common.http_pinning) so the validated answer is the one
    actually used (DNS-rebinding/TOCTOU defence)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ResolutionError("ssrf", "endpoint URL must use https")
    if parsed.username or parsed.password:
        raise ResolutionError("ssrf", "endpoint URL must not contain credentials")
    if parsed.fragment:
        raise ResolutionError("ssrf", "endpoint URL must not contain a fragment")
    host = parsed.hostname
    if not host:
        raise ResolutionError("format", "endpoint URL has no host")
    # IP literals are checked directly; names via DNS answers.
    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        try:
            candidates = dns_resolver(host)
        except Exception as exc:
            raise ResolutionError("dns", f"DNS resolution failed for {host}: {exc}") from exc
    if not candidates:
        raise ResolutionError("dns", f"no DNS answers for {host}")
    bad = [ip for ip in candidates if not _is_public_ip(ip)]
    if bad:
        raise ResolutionError(
            "ssrf", f"endpoint host resolves to non-public address(es): {bad}"
        )
    return host, candidates


def validate_endpoint_url(url: str, *, dns_resolver=default_dns_resolver) -> str:
    """Registration- and call-time URL validation (§6). Returns
    the URL unchanged or raises ResolutionError('ssrf'|'format')."""
    validated_host_ips(url, dns_resolver=dns_resolver)
    return url


def validate_address_for_network(address: str, network) -> str:
    """Chain-family address validation; returns the canonical
    form (blacklist/pipeline comparisons) or raises
    ResolutionError('wrong_network')."""
    from waas.modules.evm import keys as evm_keys
    from waas.modules.operations.dispatch import family_of
    from waas.modules.solana import keys as solana_keys
    from waas.modules.ton import addresses as ton_addresses
    from waas.modules.tron import addresses as tron_addresses

    family = family_of(network)
    try:
        if family == "evm":
            return evm_keys.normalize_address(address)
        if family == "tron":
            if not tron_addresses.is_valid(address):
                raise ValueError("invalid TRON address")
            return tron_addresses.normalize_to_hex(address)
        if family == "solana":
            if not solana_keys.is_valid_address(address):
                raise ValueError("invalid Solana address")
            return address
        if not ton_addresses.is_valid(address, testnet=network.is_testnet):
            raise ValueError("invalid TON address")
        return ton_addresses.normalize(address)
    except ValueError as exc:
        raise ResolutionError(
            "wrong_network", f"address is not valid for {network.slug}: {exc}"
        ) from exc


def resolve_destination(
    *,
    endpoint_url: str,
    signing_secret: str = "",
    network,
    asset,
    request_id: str,
    http_client: httpx.Client | None = None,
    dns_resolver=default_dns_resolver,
) -> ResolvedDestination:
    """One fresh resolution (§5). Never cached, never reused."""
    host, ips = validated_host_ips(endpoint_url, dns_resolver=dns_resolver)
    timestamp = str(int(time.time()))
    headers = {
        "X-Blockchain-Network": network.slug,
        "X-Asset-ID": str(asset.id),
        "X-WaaS-Request-ID": request_id,
        "X-WaaS-Timestamp": timestamp,
        "Accept": "text/plain",
    }
    if signing_secret:
        canonical = f"{timestamp}\n{request_id}\n{network.slug}\n{asset.id}"
        headers["X-WaaS-Signature"] = hmac.new(
            signing_secret.encode(), canonical.encode(), hashlib.sha256
        ).hexdigest()
    # Pin the socket to the first validated IP: the answer the
    # validator approved is the address actually connected to.
    client = http_client or pinned_httpx_client(
        host=host,
        ip=ips[0],
        timeout=httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT),
    )
    last_error: Exception | None = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            response = client.get(endpoint_url, headers=headers)
            break
        except httpx.HTTPError as exc:
            last_error = exc
            response = None
    if response is None:
        raise ResolutionError("transport", f"endpoint unreachable: {last_error}")
    if 300 <= response.status_code < 400:
        raise ResolutionError("redirect", "endpoint answered with a redirect (not followed)")
    if response.status_code != 200:
        raise ResolutionError("http_status", f"endpoint answered HTTP {response.status_code}")
    body = response.content
    if len(body) > MAX_BODY_BYTES:
        raise ResolutionError("too_large", f"response exceeds {MAX_BODY_BYTES} bytes")
    raw_hash = hashlib.sha256(body).hexdigest()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResolutionError("format", "response is not UTF-8 text") from exc
    address = text.strip()
    if not address:
        raise ResolutionError("format", "response body is empty")
    if any(char.isspace() for char in address) or address[0] in "{[<":
        raise ResolutionError(
            "format", "response must be exactly one plain-text address token"
        )
    normalized = validate_address_for_network(address, network)
    return ResolvedDestination(
        address=address, normalized=normalized, raw_body_sha256=raw_hash
    )
