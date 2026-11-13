"""Socket-level DNS pinning for SSRF-sensitive outbound calls.

Validating that a hostname resolves only to public IPs is not
enough on its own: a hostile or compromised DNS can answer
differently between the validation lookup and the actual connect
(rebinding / TOCTOU). These helpers build an httpx client whose
transport connects to the *already validated* IP while keeping
the original hostname for the Host header and for TLS SNI and
certificate verification — so the bytes go exactly where the
validator approved, and TLS still authenticates the real name.
"""

from __future__ import annotations

import httpx


def rewrite_request_for_pin(request: httpx.Request, *, host: str, ip: str) -> httpx.Request:
    """Point ``request`` at ``ip`` while preserving ``host`` for
    Host/SNI/certificate verification. Pure and unit-testable."""
    port = request.url.port
    host_header = host if port in (None, 443) else f"{host}:{port}"
    request.url = request.url.copy_with(host=ip)
    request.headers["Host"] = host_header
    request.extensions = {**request.extensions, "sni_hostname": host}
    return request


class PinnedTransport(httpx.HTTPTransport):
    def __init__(self, *, host: str, ip: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._host = host
        self._ip = ip

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return super().handle_request(
            rewrite_request_for_pin(request, host=self._host, ip=self._ip)
        )


def pinned_httpx_client(
    *, host: str, ip: str, timeout: httpx.Timeout | float
) -> httpx.Client:
    transport = PinnedTransport(host=host, ip=ip, verify=True)
    return httpx.Client(
        transport=transport, timeout=timeout, follow_redirects=False, trust_env=False
    )
