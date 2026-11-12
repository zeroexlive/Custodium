"""Gas-station preflight, called from the shared transfer
dispatch before any non-native transfer is executed.

Behaviour contract
------------------
- Native-asset transfers, projects without an enabled station,
  and self-funded wallets pass through untouched (returns None).
- A wallet at/above the station threshold passes through; any
  in-flight top-up for the operation is marked confirmed.
- Below the threshold, exactly one top-up per operation is
  broadcast from the station's funding wallet through the normal
  pipeline, and :class:`GasTopUpPending` is raised so the caller
  DEFERS the transfer (withdrawal stays approved; sweep returns
  to resolved) instead of failing it. The next worker pass finds
  the topped-up balance and proceeds.
- A balance that cannot be read never blocks a transfer.
"""

from __future__ import annotations

from django.utils import timezone

from waas.modules.assets.models import Asset
from waas.modules.audit.models import AuditEvent
from waas.modules.gasstation import balances
from waas.modules.gasstation.models import GasStation, GasTopUp


class GasTopUpPending(Exception):
    """Control-flow signal: the transfer must wait for gas."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _wallet_address(wallet, network) -> str | None:
    address = wallet.addresses.filter(network=network).order_by("created_at").first()
    return address.address if address else None


def _native_asset(network) -> Asset | None:
    return Asset.objects.filter(network=network, token_standard="native").first()


def _refresh_topup(topup: GasTopUp, *, factories) -> None:
    """Sync a top-up's status from its chain transaction row."""
    if topup.status in (GasTopUp.Status.CONFIRMED, GasTopUp.Status.FAILED):
        return
    if not topup.chain_tx_id:
        return
    from waas.modules.operations import dispatch

    model = dispatch.chain_tx_model(dispatch.family_of(topup.network))
    row = model.objects.filter(id=topup.chain_tx_id).first()
    if row is None:
        return
    try:
        # Advancing the row also settles the funding wallet's
        # ledger reservation once the chain confirms the top-up.
        dispatch.confirm(row, network=topup.network, factories=factories)
        row.refresh_from_db()
    except Exception:
        pass
    status = getattr(row, "status", "")
    value = getattr(status, "value", status)
    if value == "confirmed":
        topup.status = GasTopUp.Status.CONFIRMED
        topup.save(update_fields=["status", "updated_at"])
    elif value in ("reverted", "failed", "dropped"):
        topup.status = GasTopUp.Status.FAILED
        topup.failure_reason = f"top-up transaction {value}"
        topup.save(update_fields=["status", "failure_reason", "updated_at"])


def preflight_transfer(
    *,
    wallet,
    network,
    asset,
    operation_key: str,
    factories,
) -> None:
    """Raise :class:`GasTopUpPending` when the transfer must wait
    for a gas top-up; return silently in every other case."""
    if asset.token_standard == "native":
        return
    station = (
        GasStation.objects.filter(project=wallet.project, network=network, enabled=True)
        .select_related("funding_wallet")
        .first()
    )
    if station is None or station.funding_wallet_id == wallet.id:
        return
    address = _wallet_address(wallet, network)
    if address is None:
        return
    provider = factories.provider(network)
    balance = balances.native_balance(provider=provider, network=network, address=address)
    if balance is None:
        return  # never block a transfer on an unreadable balance

    topup = GasTopUp.objects.filter(operation_key=operation_key).first()
    if balance >= int(station.min_native_balance):
        if topup is not None and topup.status == GasTopUp.Status.BROADCAST:
            _refresh_topup(topup, factories=factories)
            if topup.status != GasTopUp.Status.CONFIRMED:
                # The balance itself is the ground truth that the
                # top-up landed; the row settles on its own track.
                topup.status = GasTopUp.Status.CONFIRMED
                topup.save(update_fields=["status", "updated_at"])
        return

    if topup is not None:
        _refresh_topup(topup, factories=factories)
        if topup.status == GasTopUp.Status.CONFIRMED:
            raise GasTopUpPending(
                "gas top-up confirmed on-chain but the wallet balance is "
                "still below the station threshold; manual review advised"
            )
        if topup.status in (GasTopUp.Status.PENDING, GasTopUp.Status.BROADCAST):
            raise GasTopUpPending("awaiting gas top-up confirmation")
        # A failed top-up falls through: a fresh attempt is allowed
        # subject to the daily cap.

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = GasTopUp.objects.filter(
        station=station, created_at__gte=today_start
    ).count()
    if used_today >= station.max_topups_per_day:
        raise GasTopUpPending(
            f"gas station daily top-up cap reached ({station.max_topups_per_day})"
        )

    native = _native_asset(network)
    if native is None:
        return
    if topup is None:
        topup = GasTopUp(
            station=station,
            target_wallet=wallet,
            network=network,
            amount=station.topup_amount,
            operation_key=operation_key,
        )
    else:
        topup.status = GasTopUp.Status.PENDING
        topup.failure_reason = ""
    topup.save()

    from waas.modules.operations import dispatch

    try:
        chain_tx = dispatch.execute_transfer(
            wallet=station.funding_wallet,
            network=network,
            asset=native,
            to_address=address,
            amount=int(station.topup_amount),
            idempotency_key=f"gas:{operation_key}",
            factories=factories,
        )
    except Exception as exc:
        topup.status = GasTopUp.Status.FAILED
        topup.failure_reason = f"top-up dispatch failed: {exc}"[:500]
        topup.save(update_fields=["status", "failure_reason", "updated_at"])
        raise GasTopUpPending(f"gas top-up could not be dispatched: {exc}") from exc

    topup.status = GasTopUp.Status.BROADCAST
    topup.chain_tx_id = str(chain_tx.id)
    topup.chain_tx_hash = dispatch.chain_tx_hash(chain_tx, dispatch.family_of(network))
    topup.save(update_fields=["status", "chain_tx_id", "chain_tx_hash", "updated_at"])
    AuditEvent.record(
        "gasstation.topup_broadcast",
        organization=wallet.project.organization,
        project=wallet.project,
        metadata={
            "topup_id": str(topup.id),
            "network": network.slug,
            "target_wallet": str(wallet.id),
            "amount": str(station.topup_amount),
            "operation_key": operation_key,
        },
    )
    raise GasTopUpPending("gas top-up broadcast; awaiting confirmation")
