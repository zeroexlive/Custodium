# ADR 0001: Django Modular Monolith with Isolated MPC and Workers

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Phase 0 (Architecture / Security) and Phase 1 (SaaS Foundation)

## Status

Proposed and accepted as the working architecture for Phase 0 and Phase 1 only. This decision is NOT Production Approved. It must be re-reviewed before any
mainnet funds, production signing, or external customer custody is enabled. See "Review triggers" at the end of this ADR.

## Context

Custodium is an enterprise, multi-chain, multi-tenant Wallet-as-a-Service (WaaS) platform. The mandated stack is:

- Backend: Django / Django Ninja, PostgreSQL, Redis, Temporal
- Frontend: Vue 3, TypeScript, Tailwind CSS
- Signing: Rust threshold ECDSA (CGGMP family) and FROST Ed25519 services
- Chains (roadmap): Ethereum, BSC, TRON, Solana, TON, plus USDT and
  arbitrary ERC-20 / equivalent tokens

The platform must provide, over time:

- Multi-tenant organisations, projects, users, roles, and API keys
- Wallet and address management across heterogeneous chains
- Deposit detection, indexing, and balance lookup
- Withdrawal approval and signing orchestration
- Sweeping and treasury operations
- A double-entry ledger with exact integer money (ADR 0007)
- Audit logging, idempotency, and strong tenant isolation

Constraints that shape this decision:

1. The team is small at Phase 0/1. Operational simplicity matters more
   than theoretical horizontal scalability on day one.
2. Custody is security-critical. The component that touches key shares
   must have the smallest possible attack surface and must not be reachable through the public web application.
3. Most early work is CRUD, tenancy, auth, and workflow orchestration —
   not high-throughput data-plane traffic.
4. Transactions spanning ledger, wallet state, and workflow state are
   far easier to reason about inside one relational database than across distributed services.
5. Premature microservices would impose distributed transactions,
   service discovery, versioned inter-service contracts, and a much larger deployment / observability burden before product fit exists.

## Decision

Adopt a **Django modular monolith** for the SaaS control plane, with **strictly isolated out-of-process components** where the risk profile
demands it:

### 1. Modular monolith (Django application)

- One Django codebase, one deployable web application for Phase 1.
- Code is organised into bounded modules, for example:
  `identity`, `tenancy`, `projects`, `api_keys`, `wallets`, `assets`, `ledger`, `withdrawals`, `deposits`, `sweeps`, `audit`, `billing`.
- Each module owns its models, services, API schemas, and tests.
- Cross-module calls go through explicit service-layer functions,
  never through importing another module's models ad hoc.
- A single PostgreSQL database is the system of record in Phase 1,
  with tenant scoping enforced in the service and query layers (see ADR 0007 and the Phase 1 acceptance criteria).
- Django Ninja provides the typed, OpenAPI-documented HTTP API.

### 2. Isolated MPC signing services (Rust, out of process)

- Threshold signing is NEVER implemented inside Django.
- MPC nodes / coordinators run as separate Rust processes, on
  separate hosts in any non-trivial deployment, communicating over authenticated, encrypted channels.
- Django may *request* a signing ceremony via Temporal activities
  (ADR 0003); it never holds a complete private key or a quorum of shares, and it never reconstructs a key.
- See ADR 0004 for the candidate protocols and their review status.

### 3. Isolated workers

- Temporal workers execute long-running, retryable workflows:
  withdrawals, sweeps, deposit reconciliation, signing orchestration.
- Chain indexers / RPC pollers run as separate worker processes,
  not inside the web request cycle.
- Redis is used for caching, rate limiting, and ephemeral queues
  only — never as the ledger or workflow source of truth.

### 4. Frontend

- Vue 3 + TypeScript + Tailwind as a separate frontend application
  consuming the Django Ninja API. It holds no secrets and makes no custody decisions; all authorisation is enforced server-side.

## Consequences

### Positive

- Fast Phase 1 delivery: one codebase, one migration history, one
  test suite, one Docker Compose stack for local development.
- Strong transactional consistency for ledger + wallet state.
- Simple, auditable tenant-isolation testing in a single process.
- Clear extraction path: a module with stable service boundaries can
  be split into a service later, when load or team size justifies it.
- MPC isolation is preserved from day one despite the monolith —
  the highest-risk component is not part of the web application.

### Negative

- The monolith is a single scaling unit for web traffic; very high
  API load would require scaling the whole application at first.
- Module boundaries are enforced by convention and code review, not
  by network boundaries. Discipline and linting / import rules are required to prevent the monolith degrading into a "big ball of mud".
- A defect in the web application can affect all control-plane
  features at once (though never, by design, signing keys directly).
- Some future workloads (for example high-volume indexing) may need
  to be extracted earlier than planned.

### Neutral / mitigations

- Enforce module boundaries with documented ownership, service-layer
  APIs, and automated import checks in CI as Phase 1 matures.
- Keep all long-running work in Temporal so web processes stay thin
  and stateless apart from the database session.

## Alternatives Considered

### A. Microservices from day one — Rejected for Phase 0/1

- Pros: independent scaling, hard network boundaries per service.
- Cons: distributed transactions for the ledger, service mesh /
  discovery overhead, versioned contracts before requirements are stable, far heavier local development and testing, and a larger
  operational surface for a small team.
- Revisit only if a Review trigger below fires.

### B. Monolith including in-process signing — Rejected absolutely

- Holding key material or implementing threshold protocols inside
  the Django process would collapse the security boundary between the internet-facing application and custody. Never acceptable.

### C. Serverless / function-per-endpoint — Rejected

- Poor fit for long-running signing ceremonies, indexing loops, and
  Temporal-orchestrated workflows; cold starts and opaque state complicate auditability.

### D. A different primary framework (FastAPI-only, Go, Node) — Rejected

- The stack is mandated: Django brings the ORM, migrations, admin,
  auth ecosystem, and mature security posture the SaaS foundation needs. Django Ninja adds modern typed APIs on top of it.

## Security Considerations

- The web monolith is internet-facing and therefore treated as the
  least trusted custody-adjacent component: it holds no complete private keys and no quorum of MPC shares.
- MPC services accept requests only from authenticated internal
  callers (mTLS or equivalent in real deployments), with allow-listed ceremony types and full audit logging.
- Worker and indexer credentials are scoped per chain / per task and
  stored via environment / secret management, never in the repo.
- Tenant isolation is a security property, not a convenience: every
  query path must be tenant-scoped and covered by isolation tests.
- The modular structure must not create a false sense of isolation:
  modules share a process and a database, so authorisation checks belong in the service layer on every operation.
- No claim in this ADR authorises production custody. Production
  requires independent security review (see Roadmap Phase 12).

## Review Triggers

Re-open this ADR if any of the following occurs:

- Sustained API or indexing load that the monolith cannot serve
  within agreed latency / throughput budgets.
- Team growth to multiple independent squads owning disjoint domains.
- A compliance or customer requirement for physically separated
  services or data residency per tenant.
- A security review finding that module-level (in-process) separation
  is insufficient for a specific component.
- Before ANY production approval, mainnet funds, or external launch —
  this ADR must be re-reviewed in full, regardless of other triggers.
