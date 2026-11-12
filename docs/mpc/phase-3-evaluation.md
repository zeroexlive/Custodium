# Phase 3 Evaluation Record — MPC Integration (Test-Only)

Status: Phase 3 evaluation. **Production signing remains disabled.**
Nothing in this record is a security review, and neither candidate
is "Production Approved". The independent-review package lives in
`docs/mpc/review/` and is **not commissioned** as of this record.

Method: pinned versions of each candidate were executed — not just
read — in the test-only harness (`services/mpc/crates/eval_harness/`),
running real DKG and threshold-signing ceremonies with ephemeral
in-memory keys over an in-memory simulated network, and verifying
the outputs with independent implementations (k256 for ECDSA,
ed25519-zebra for Ed25519).

## 1. Pin record

| Crate | Pinned | Role |
|-------|--------|------|
| `frost-ed25519` | `=3.0.0` | FROST (RFC 9591) Ed25519 |
| `frost-core` | 3.0.0 (via frost-ed25519) | FROST protocol core |
| `cggmp24` | `=0.7.0-alpha.2` | CGGMP-family threshold ECDSA (secp256k1) |
| `cggmp24-keygen` | `=0.7.0-alpha.2` | pinned explicitly — see §3.3 |
| `paillier-zk` | `=0.7.0-alpha.2` | pinned explicitly — see §3.3 |
| `fast-paillier` | 0.3.x, feature `backend-rug` | Paillier arithmetic on GMP |
| `round-based` | `=0.4.2` | protocol runtime / simulated network |

The full dependency set is locked in `services/mpc/Cargo.lock`
(committed). Exact (`=`) pins are deliberate: see the alpha-drift
finding in §3.3.

## 2. FROST Ed25519 — `frost-ed25519` 3.0.0

### Executed (2026-11-12, this workspace)
- DKG (Pedersen-style, `keys::dkg` part 1/2/3) for 2-of-3: all
  participants derived key packages and agreed on one group
  verifying key.
- Threshold signing by three different quorums ({1,2}, {2,3}, {1,3}):
  aggregated signatures verify against the group key.
- Below-threshold attempt (1 signer) fails, as required.
- Signature does not verify for a tampered message.
- **Cross-implementation check:** the group signature verifies with
  `ed25519-zebra` as a plain Ed25519 signature — i.e. FROST output
  is chain-standard for Solana/TON.
- Harness tests: 4 passed.

### Audit provenance
NCC Group's 2023 audit covered the ZF FROST codebase at an earlier
release line. **3.0.0 is a descendant of that codebase, not the
audited artifact.** Treat the audit as lineage evidence only; the
pinned version requires the commissioned review (`docs/mpc/review/`).

### Notes
- FROST refresh (`keys::refresh`) exists in frost-core 3.0.0
  (dealerless DKG-based refresh); executing it is scheduled with the
  production-path build, not this evaluation.
- Identifiers in the evaluation are sequential integers; production
  identifier assignment is part of the transport/ceremony design
  review scope.

## 3. Threshold ECDSA — the CGGMP family

### 3.1 `cggmp21` is REJECTED as the production candidate

Phase 0 named `dfns/cggmp21` the ECDSA candidate. Phase 3 research
found that position untenable:

- **CVE-2025-66016 / RUSTSEC-2025-0129 (Critical, CVSS 9.3):** a
  missing ZK-proof check in `cggmp21 < 0.6.3` lets a single
  malicious signer accumulate enough material across rounds to
  **reconstruct the full ECDSA private key**. Fixed in 0.6.3
  (2025-11-24).
- **RUSTSEC-2025-0127 (CVE-2025-66017, High):** signature forgery
  via altered presignatures. The advisory lists **no patched
  `cggmp21` version**; the maintainers' fix path is migration to
  `cggmp24 0.7.0-alpha.2`. Relatedly, presignatures combined with
  HD derivation reduce effective security (≈85 bits) — presignature
  use needs explicit review either way.
- The vendor (DFNS) migrated its own signer to `cggmp24`
  (2025-10/2026-01 release notes), and the codebase moved to the
  Linux Foundation's LFDT Lockness project.

Decision: `cggmp21` (any version) is not adopted. 0.6.3 closes the
key-reconstruction hole but leaves the presignature-forgery class
unpatched with no fix line. Recorded here so the rejection is not
re-litigated without new evidence.

### 3.2 `cggmp24` 0.7.0-alpha.2 — evaluated

Executed (2026-11-12, this workspace):

- Aux-info generation (Paillier, SecurityLevel128), threshold DKG
  (2-of-3), and threshold signing by parties {0, 2}; all signing
  parties produced the identical signature; the library's
  `Signature::verify` accepted it; k256 verified it independently
  as a standard secp256k1 ECDSA signature over the SHA-256 digest.
- Harness tests: 5 passed total (4 FROST + this ceremony).
- Timing: the ceremony test took ≈377 s wall-clock in a **debug**
  build on this project's small shared VM (1.5 vCPU). The dominant
  cost is safe-prime generation for the Paillier aux data. This
  number characterises this environment only — it is not a
  production performance claim in either direction.

Limitations and risks (all recorded, none waived):
- **Alpha software.** 0.7.0-alpha.2 is a prerelease. API and
  protocol details may change; see §3.3 for the drift we already hit.
- **No key refresh.** The alpha implements neither threshold nor
  non-threshold refresh (the crate docs say so explicitly).
  `cggmp21` had non-threshold refresh. Until refresh exists or the
  review accepts the compensating control (re-key by new DKG +
  asset migration), share rotation is a migration event, not a
  ceremony.
- **No identifiable abort** in the implementation (docs state this),
  although the underlying paper family supports it.
- **Threshold support is the implementers' extension:** CGGMP24 the
  paper is non-threshold (n-of-n); the t-of-n keygen/signing in this
  crate is a "CGGMP24-like" protocol defined by the implementers'
  spec. It is precisely the part with the least external scrutiny —
  a headline item for the commissioned review.
- **Audit status:** the Kudelski report linked from the crate is
  the audit of the `cggmp21` codebase. The cggmp24 alpha line is
  **not** itself audited. Lineage evidence only.
- **Backend:** the alpha is written against the rug/GMP backend of
  `paillier-zk` (the num-bigint backend does not compile it).
  Building requires a C toolchain and `m4` (gmp-mpfr-sys builds GMP
  from source). Backend side-channel posture is a review question.
- **Cost:** safe-prime generation for aux data is expensive
  (minutes-scale for a 3-party set on small hardware). Aux data is
  reusable across keys for a fixed signer set per the crate docs —
  that reuse is itself a review question (scope §B.1).

### 3.3 Alpha drift — a concrete finding

With `cggmp24 = "=0.7.0-alpha.2"` declared, Cargo's prerelease
range rules still resolved `paillier-zk` and `cggmp24-keygen` to
**0.7.0-alpha.4**, whose API changes (e.g. the `paillier_zk::rug`
re-export moved) break the alpha.2 build. Remedy applied: exact
pins for those two crates in the harness manifest + committed
`Cargo.lock`. Lesson recorded for the production build: in the
alpha line, *the lockfile is part of the pin*, and every lockfile
update is a security-relevant change requiring re-verification.

## 4. CVE / advisory watch (started 2026-11-12)

| ID | Affects | Status for Custodium |
|----|---------|----------------------|
| CVE-2025-66016 / RUSTSEC-2025-0129 | `cggmp21 < 0.6.3` — full key reconstruction | Not adopted (§3.1) |
| CVE-2025-66017 / RUSTSEC-2025-0127 | `cggmp21` presignature forgery — no patched version | Not adopted; cggmp24 exposure to this class is review question §B.2 |
| CVE-2023-33241 (BitForge) | GG18/GG20 implementations (not used) | Background — reason GG-family elders were never candidates |
| TSSHOCK disclosures | Some CGGMP21 deployments | Background for ceremony-design review |

Watch process: check RustSec + upstream release notes on every
dependency update and at least monthly (Phase 12 operationalises
this with alerting). This table is a log, not a monitoring system.

## 5. Phase 3 exit criteria — honest assessment

Backlog exit criteria for Phase 3 were: (a) testnet signing works
end-to-end for the evaluated suites; (b) independent review reports
received.

- (a) **Met at protocol level, not yet at chain level.** Both
  suites completed real DKG + threshold signing with independently
  verified standard signatures. There is no chain or testnet
  integration until Phase 4 (Ethereum & BSC) by design.
- (b) **NOT met.** The review package is prepared
  (`docs/mpc/review/`); commissioning is the project owner's
  action. Until reports are received and findings dispositioned:
  production signing stays disabled, wallets stay `provisioning`,
  address generation stays gated, and no Custodium material may
  describe the MPC stack as reviewed or production-ready.

Phase 3 therefore lands as **Implemented (evaluation)** — the
evaluation deliverables are complete; the phase's production gate
remains closed pending (b).

## 6. Temporal orchestration (ADR 0003)

The harness drives ceremonies with the `round-based` runtime over
a simulated network. The production mapping, to be built with the
post-review coordinator: each protocol (aux-gen, keygen, signing)
is a Temporal activity set executed by the signer services; the
workflow owns session state, timeouts, and abort cleanup; the
coordinator holds no shares at any point. This mapping is a design
statement only in Phase 3 — no Temporal MPC workflow is implemented
or claimed here. Ceremony-protocol code that production will reuse
must come through the commissioned review first.
