"""HMAC-SHA256 machine-request signing (see docs/api/authentication.md).

Canonical string (UTF-8, newline-joined, signature version v1):
    METHOD \n PATH_WITH_QUERY \n TIMESTAMP \n NONCE \n SHA256_HEX(BODY)
Signature = hex(HMAC_SHA256(secret, canonical))
"""
from __future__ import annotations

import hashlib
import hmac


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def canonical_string(method: str, path_with_query: str, timestamp: str, nonce: str, body: bytes) -> str:
    return "\n".join([method.upper(), path_with_query, timestamp, nonce, body_digest(body)])


def sign(secret: str, method: str, path_with_query: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = canonical_string(method, path_with_query, timestamp, nonce, body)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify(secret: str, expected_signature: str, method: str, path_with_query: str,
           timestamp: str, nonce: str, body: bytes) -> bool:
    computed = sign(secret, method, path_with_query, timestamp, nonce, body)
    return hmac.compare_digest(computed, (expected_signature or "").lower())
