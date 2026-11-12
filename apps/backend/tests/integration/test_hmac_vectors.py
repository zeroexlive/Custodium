"""The published HMAC test vectors (docs/api/hmac-test-vectors.md)
must always match the production signers — documentation that
drifts from the implementation is a security bug for integrators.
"""

from __future__ import annotations

from waas.modules.webhooks.services import sign as webhook_sign
from waas.security.hmac.signing import sign

SECRET = "test-secret-for-vectors"


def test_api_hmac_vectors() -> None:
    body = b'{"wallet_id":"wal_example","amount":"1000"}'
    assert (
        sign(SECRET, "POST", "/api/v1/withdrawals", "1790000000", "vector-nonce-1", body)
        == "dd03ad097b410325af8b78f17ef17a0f580059f1fa14fb2bd2b70631c2d215e3"
    )
    assert (
        sign(SECRET, "GET", "/api/v1/wallets?project_id=proj_example",
             "1790000100", "vector-nonce-2", b"")
        == "d4323beb307ca673c5ea7b4c88fff7854b8ddccc2d9fa69d4cdf9fe9d12d27f3"
    )


def test_webhook_signature_vector() -> None:
    assert (
        webhook_sign("whsec_example", 1790000000, b'{"id":"evt"}')
        == "bc211a39537d1a2ef87299dd139aee3507b2026c4346927c26431e9fb7604161"
    )
