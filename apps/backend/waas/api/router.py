from __future__ import annotations

from ninja import NinjaAPI, Router

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.modules.api_credentials.api.router import router as api_credentials_router
from waas.modules.assets.api.router import router as assets_router
from waas.modules.audit.api.router import router as audit_router
from waas.modules.blacklist.api.router import router as blacklist_router
from waas.modules.identity.api.router import router as identity_router
from waas.modules.indexing.api.router import router as indexing_router
from waas.modules.ledger.api.router import router as ledger_router
from waas.modules.networks.api.router import router as networks_router
from waas.modules.operations.api.router import dashboard_router as operations_dashboard_router
from waas.modules.operations.api.router import operator_router
from waas.modules.operations.api.router import router as operations_router
from waas.modules.organizations.api.router import router as organizations_router
from waas.modules.plans.api.router import router as plans_router
from waas.modules.projects.api.router import router as projects_router
from waas.modules.sweeps.api.router import dashboard_router as sweeps_dashboard_router
from waas.modules.sweeps.api.router import router as sweeps_router
from waas.modules.wallets.api.router import router as wallets_router
from waas.modules.webhooks.api.router import dashboard_router as webhooks_dashboard_router
from waas.modules.webhooks.api.router import router as webhooks_router

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
api.add_router("", indexing_router)
api.add_router("", operations_router)
api.add_router("", operations_dashboard_router)
api.add_router("", operator_router)
api.add_router("", sweeps_router)
api.add_router("", sweeps_dashboard_router)
api.add_router("", webhooks_router)
api.add_router("", webhooks_dashboard_router)
api.add_router("", plans_router)

# ---------------------------------------------------------------------------
# Phase gates: endpoints whose contracts exist in the dashboard/API design but
# whose subsystems land in later phases. They fail honestly with 501 instead
# of returning fabricated data.
# ---------------------------------------------------------------------------
phase_router = Router(tags=["phase-gates"])
any_auth = AnyAuth()
dashboard_auth = DashboardAuth()


api.add_router("", phase_router)
