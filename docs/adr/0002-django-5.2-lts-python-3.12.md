# ADR 0002: Django 5.2 LTS on Python 3.12

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Phase 0 (Architecture / Security) and Phase 1 (SaaS Foundation)

## Status

Proposed and accepted as the working platform choice for Phase 0 and
Phase 1 only. This decision is NOT Production Approved. Versions must
be re-verified and patched continuously; see "Review triggers".

## Context

Custodium is a custody platform. For custody, the relevant question
is not "what is newest?" but "what will still receive security fixes
for the whole period this code is expected to run, without forcing a
major framework upgrade under time pressure?"

Verified facts (checked 2026-11-12):

- Django 5.2 is a Long-Term Support (LTS) release.
  Django 5.2 LTS is supported until April 2028.
- The latest 5.2 patch release at verification time was Django
  5.2.19, released 3 November 2026.
- Django 6.1 exists and is newer, but it is NOT an LTS release and
  therefore has a materially shorter support window than 5.2 LTS.
  Chasing 6.1 would mean planning a major upgrade much sooner, for
  no custody-relevant feature gain identified in Phase 0.
- Python 3.12 is a supported, stable Python line for Django 5.2 and
  is the newest Python version the project is willing to pin for
  Phase 1 without re-validating the full dependency set (Temporal
  SDK, database drivers, cryptography-adjacent libraries).

Additional context:

- The API layer is Django Ninja on top of Django, providing Pydantic-
  based schemas, typed request/response validation, and OpenAPI docs.
- The team needs reproducible environments across developer machines,
  CI, and Docker: identical interpreter, identical dependency set.
- Custody code must be boring and predictable. Unplanned framework
  churn is itself a security and reliability risk.

## Decision

1. **Framework: Django 5.2 LTS**, pinned to the latest 5.2.x patch
   release at lockfile generation time (5.2.19 at verification), and
   updated promptly as new 5.2.x security/bugfix releases appear.
2. **Python: 3.12** (latest stable 3.12.x patch at build time).
   No production use of pre-release or end-of-life interpreters.
3. **API framework: Django Ninja**, pinned, built on the Django 5.2
   application defined in ADR 0001.
4. **Dependency management: `uv`** for fast, deterministic installs
   and lockfile-based reproducibility.
   - `pyproject.toml` declares direct dependencies with compatible-
     release bounds.
   - A lockfile (`uv.lock`) is committed and is the source of truth
     for CI and Docker builds. Floating installs are forbidden.
   - Hash / lock verification is used in CI where supported.
5. **Pinning policy:**
   - Framework, database drivers, auth/crypto-adjacent libraries,
     and the Temporal SDK are pinned exactly via the lockfile.
   - Patch upgrades within the Django 5.2 LTS line are routine and
     expected; minor/major framework upgrades are deliberate events
     requiring a changelog review, full test run, and staging soak.
6. **Upgrade policy:**
   - Track Django and Python security announcements.
   - Apply Django security releases on an expedited cadence.
   - Plan the next LTS migration (successor LTS after 5.2) well
     before April 2028 — migration work starts no later than
     6 months before end of support, earlier if Phase 12 requires it.
   - Never run an end-of-life Django or Python in any environment
     that can reach real data or real funds.

## Consequences

### Positive

- Security support until April 2028 from the 5.2 LTS line gives the
  platform a long, predictable runway through Phases 1–12 planning.
- Patch-only maintenance for the framework reduces regression risk
  during the most security-sensitive build-out phases.
- `uv` + lockfile gives fast, reproducible CI and Docker builds and
  makes "works on my machine" dependency drift detectable.
- Django 5.2 + Ninja is a well-understood combination with mature
  documentation, easing hiring, review, and external audit.

### Negative

- The project deliberately forgoes features that debut in Django
  6.x until a later, planned LTS migration.
- Staying on Python 3.12 means newer interpreter performance or
  language features (3.13+) are unavailable until re-validation.
- LTS discipline requires calendar ownership: someone must own the
  April 2028 deadline and the patch cadence, or the benefit is lost.

### Neutral / mitigations

- Feature gaps in 5.2 are assessed per need; a single missing feature
  does not justify abandoning LTS — build it in application code or
  wait for the planned LTS migration.

## Alternatives Considered

### A. Django 6.1 (newest feature release) — Rejected

- Newer, but non-LTS with a shorter support window. For a custody
  platform, trading years of guaranteed security support for
  incremental features is the wrong trade in Phase 0/1.

### B. Django 4.2 LTS (older LTS) — Rejected

- Also LTS, but older, with an earlier end-of-support date and a
  smaller remaining runway than 5.2. No reason to start behind.

### C. Track Django main / unpinned dependencies — Rejected absolutely

- Non-reproducible builds are unacceptable for custody software and
  for security review: reviewers must be able to rebuild exactly
  what was reviewed.

### D. pip + requirements.txt without a lockfile — Rejected

- Slower, weaker resolution guarantees than `uv` with a committed
  lockfile. `requirements` exports may still be generated for tooling
  that needs them, but the lockfile remains authoritative.

### E. Newer Python (3.13+) immediately — Deferred, not rejected

- Revisit once the full dependency set (especially Temporal and
  native extensions) is validated on it in CI. Stability wins first.

## Security Considerations

- The primary security value of LTS is a guaranteed stream of
  security fixes. That value is realised only if patch releases are
  actually applied promptly — see the upgrade policy above.
- Pinning must never become an excuse to freeze on a vulnerable
  patch release. "Pinned" means "pinned to a known, patched version
  via the lockfile", not "never updated".
- Dependency additions require review: new packages enter the
  lockfile only via a reviewed change, with attention to maintainer
  health, release signing, and transitive dependencies.
- CI should run dependency vulnerability scanning against the
  lockfile and fail on known critical vulnerabilities.
- Docker base images pin the Python 3.12 patch version and are
  rebuilt regularly to pick up OS-level security updates.
- No secrets are baked into images or the lockfile; configuration
  and credentials come from the environment / secret store.

## Review Triggers

Re-open this ADR if any of the following occurs:

- A Django or Python security release that cannot be applied on the
  5.2 / 3.12 lines (for example a fix shipped only in a newer line).
- Django announces a successor LTS, or 12 months remain before the
  April 2028 end of support for 5.2 LTS — whichever comes first.
- A required dependency drops support for Django 5.2 or Python 3.12.
- Python 3.12 approaches end-of-life, or the validated dependency
  set fully supports a newer stable Python in CI.
- Before ANY production approval — re-verify the current patch
  versions, support dates, and vulnerability status in full.
