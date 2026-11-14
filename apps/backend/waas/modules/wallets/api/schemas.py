from __future__ import annotations

from ninja import Schema


class WalletIn(Schema):
    project_id: str | None = None  # dashboard auth only; machine keys imply it
    label: str
    external_customer_id: str = ""
    wallet_type: str = "mpc_threshold"


class WalletStatusIn(Schema):
    status: str  # frozen | active | archived


class AddressCreateIn(Schema):
    network: str  # network slug


class ResolveIn(Schema):
    project_id: str | None = None
    external_customer_id: str
    network: str  # network slug


class DepositAddressIn(Schema):
    """Create (or return) the deposit address for one of the
    customer's end users, identified by the customer's own UID
    (``external_customer_id``), on one network."""

    project_id: str | None = None  # dashboard auth only; machine keys imply it
    external_customer_id: str
    network: str  # network slug


def wallet_out(wallet: object) -> dict:
    return {
        "id": str(wallet.id),  # type: ignore[attr-defined]
        "project_id": str(wallet.project_id),  # type: ignore[attr-defined]
        "label": wallet.label,  # type: ignore[attr-defined]
        "external_customer_id": wallet.external_customer_id,  # type: ignore[attr-defined]
        "wallet_type": wallet.wallet_type,  # type: ignore[attr-defined]
        "status": wallet.status,  # type: ignore[attr-defined]
        "key_generation": {
            "ecdsa_key_ref": wallet.ecdsa_key_ref,  # type: ignore[attr-defined]
            "ed25519_key_ref": wallet.ed25519_key_ref,  # type: ignore[attr-defined]
        },
        "policy_name": wallet.policy_name,  # type: ignore[attr-defined]
        "policy_version": wallet.policy_version,  # type: ignore[attr-defined]
        "created_at": wallet.created_at.isoformat() if wallet.created_at else None,  # type: ignore[attr-defined]
    }


def address_out(address: object) -> dict:
    return {
        "id": str(address.id),  # type: ignore[attr-defined]
        "wallet_id": str(address.wallet_id),  # type: ignore[attr-defined]
        "network": address.network.slug,  # type: ignore[attr-defined]
        "address": address.address,  # type: ignore[attr-defined]
        "derivation_path": address.derivation_path,  # type: ignore[attr-defined]
        "derivation_index": address.derivation_index,  # type: ignore[attr-defined]
        "memo": address.memo,  # type: ignore[attr-defined]
        "status": address.status,  # type: ignore[attr-defined]
        "created_at": address.created_at.isoformat() if address.created_at else None,  # type: ignore[attr-defined]
    }
