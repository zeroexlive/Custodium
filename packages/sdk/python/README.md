# Custodium Python SDK — Planned (Phase 0)

No SDK is implemented yet. This directory is a Phase 0 placeholder.

When implemented, the SDK will:

- Target the OpenAPI contract in `packages/contracts/openapi/` (itself
  not yet published).
- Authenticate server-to-server requests with the platform's
  **HMAC-SHA256** scheme — API key ID + method + canonical path/query +
  body digest + timestamp + unique nonce, verified server-side with
  replay protection. See the Phase 0 authentication / API-credential
  design in `docs/api/authentication.md`.
- Never embed API secrets in browser-executed code, and never send
  secrets in query parameters.
