from __future__ import annotations

from ninja import NinjaAPI, Router
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.modules.api_credentials.api.router import router as api_credentials_router
from waas.modules.assets.api.router import router as assets_router
from waas.modules.audit.api.router import router as audit_router
from waas.modules.blacklist.api.router import router as blacklist_router
from waas.modules.identity.api.router import router as identity_router
from waas.modules.ledger.api.router import router as ledger_router
from waas.modules.networks.api.router import router as networks_router
from waas.modules.organizations.api.router import router as organizations_router
from waas.modules.projects.api.router import router as projects_router
from waas.modules.wallets.api.router import router as wallets_router

# All APIs here authenticate with bearer tokens or HMAC signatures, never
# cookie sessions, so Django's cookie CSRF threat model does not apply to
# them. If cookie-based dashboard sessions are introduced, they must be
# served with CSRF protection (see docs/api/authentication.md).
api = NinjaAPI(title="Custodium WaaS API", version="1.0.0")

api.add_router("", identity_router)
api.add_router("", organizations_router)
api.add_router("", projects_router)
api.add_router("", api_credentials_router)
api.add_router("", networks_router)
api.add_router("", assets_router)
api.add_router("", audit_router)
api.add_router("", wallets_router)
api.add_router("", ledger_router)
api.add_router("", blacklist_router)

# ---------------------------------------------------------------------------
# Phase gates: endpoints whose contracts exist in the dashboard/API design but
# whose subsystems land in later phases. They fail honestly with 501 instead
# of returning fabricated data.
# ---------------------------------------------------------------------------
phase_router = Router(tags=["phase-gates"])
any_auth = AnyAuth()
dashboard_auth = DashboardAuth()


@phase_router.get("/transactions/lookup", auth=any_auth)
def transaction_lookup_not_implemented(request, network: str, hash: str):
    raise HttpError(
        501,
        "Transaction indexing and hash lookup are not available until Phase 5. "
        "No result is returned rather than an unverified one.",
    )


@phase_router.get("/sweep-destination-endpoint", auth=dashboard_auth)
def sweep_endpoint_get_not_implemented(request):
    raise HttpError(501, "Sweep destination endpoint registration arrives in Phase 10.")


@phase_router.put("/sweep-destination-endpoint", auth=dashboard_auth)
def sweep_endpoint_put_not_implemented(request):
    raise HttpError(501, "Sweep destination endpoint registration arrives in Phase 10.")


@phase_router.delete("/sweep-destination-endpoint", auth=dashboard_auth)
def sweep_endpoint_delete_not_implemented(request):
    raise HttpError(501, "Sweep destination endpoint registration arrives in Phase 10.")


api.add_router("", phase_router)
