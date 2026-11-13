from .base import *  # noqa: F401,F403

DEBUG = False
EXPOSE_TOKEN_IN_RESPONSE = False
if SECRET_KEY.startswith("dev-only"):  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")
if len(SECRET_KEY) < 32:  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be at least 32 characters in production")
if not WAAS_SECRET_ENCRYPTION_KEY:  # noqa: F405
    raise RuntimeError("WAAS_SECRET_ENCRYPTION_KEY must be set in production (KMS/Vault-managed)")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# TLS terminates at the edge reverse proxy (see the deployment
# tutorials); trust its X-Forwarded-Proto so SECURE_SSL_REDIRECT
# does not loop on the plain-HTTP hop from proxy to gunicorn.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
