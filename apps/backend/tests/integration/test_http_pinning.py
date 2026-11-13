"""Socket-level DNS pinning: the transport connects to the
validated IP while Host/SNI keep the real hostname, and the
resolver's production path (no injected client) pins to the first
validated DNS answer.
"""

from __future__ import annotations

import httpx
import pytest

from waas.common.http_pinning import rewrite_request_for_pin
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.sweeps import resolver


def test_rewrite_points_socket_at_ip_preserving_host_and_sni() -> None:
    request = httpx.Request("GET", "https://tenant.example/resolve?x=1")
    rewritten = rewrite_request_for_pin(request, host="tenant.example", ip="93.184.216.34")
    assert rewritten.url.host == "93.184.216.34"
    assert rewritten.url.path == "/resolve"
    assert rewritten.headers["Host"] == "tenant.example"
    assert rewritten.extensions["sni_hostname"] == "tenant.example"


def test_rewrite_keeps_explicit_port_in_host_header() -> None:
    request = httpx.Request("POST", "https://hooks.example:8443/waas")
    rewritten = rewrite_request_for_pin(request, host="hooks.example", ip="93.184.216.35")
    assert rewritten.url.host == "93.184.216.35"
    assert rewritten.url.port == 8443
    assert rewritten.headers["Host"] == "hooks.example:8443"


@pytest.mark.django_db
def test_resolver_production_path_pins_validated_ip(monkeypatch) -> None:
    captured = {}

    def fake_pinned_client(*, host, ip, timeout):
        captured["host"] = host
        captured["ip"] = ip

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"0x3535353535353535353535353535353535353535")

        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(resolver, "pinned_httpx_client", fake_pinned_client)
    from django.core.management import call_command

    call_command("seed_networks_assets")
    network = BlockchainNetwork.objects.get(slug="ethereum")
    from waas.modules.assets.models import Asset

    asset = Asset.objects.get(network=network, symbol="USDT")
    result = resolver.resolve_destination(
        endpoint_url="https://tenant.example/resolve",
        signing_secret=None,
        network=network,
        asset=asset,
        request_id="pin-test-1",
        dns_resolver=lambda host: ["93.184.216.34", "93.184.216.35"],
    )
    assert result.address == "0x3535353535353535353535353535353535353535"
    assert captured == {"host": "tenant.example", "ip": "93.184.216.34"}
