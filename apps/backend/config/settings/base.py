"""Base settings for Custodium backend. Environment-specific modules import from here."""
from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = False
ALLOWED_HOSTS: list[str] = [h for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ninja",
    "waas.modules.identity",
    "waas.modules.organizations",
    "waas.modules.projects",
    "waas.modules.api_credentials",
    "waas.modules.networks",
    "waas.modules.assets",
    "waas.modules.audit",
    "waas.modules.wallets",
    "waas.modules.ledger",
    "waas.modules.blacklist",
    "waas.modules.evm",
    "waas.modules.indexing",
    "waas.modules.tron",
    "waas.modules.solana",
    "waas.modules.ton",
    "waas.modules.operations",
    "waas.modules.sweeps",
    "waas.modules.webhooks",
    "waas.modules.plans",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]

# --- Database: SQLite by default for local dev; PostgreSQL via DATABASE_URL ---
_database_url = env("DATABASE_URL")
if _database_url.startswith("postgres"):
    _p = urllib.parse.urlparse(_database_url)
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _p.path.lstrip("/"),
        "USER": urllib.parse.unquote(_p.username or ""),
        "PASSWORD": urllib.parse.unquote(_p.password or ""),
        "HOST": _p.hostname or "localhost",
        "PORT": str(_p.port or 5432),
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }}

AUTH_USER_MODEL = "identity.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Custodium specific ---
# Dedicated key for encrypting recoverable API secrets (Fernet). In production
# this MUST come from a KMS/Vault-managed secret; see waas/security/secret_management.
WAAS_SECRET_ENCRYPTION_KEY = env("WAAS_SECRET_ENCRYPTION_KEY")
# Dashboard bearer tokens (Phase 1). Cookie-based dashboard sessions are the
# documented production direction (docs/api/authentication.md); bearer tokens
# are hashed at rest, revocable and expire.
DASHBOARD_TOKEN_TTL_HOURS = int(env("DASHBOARD_TOKEN_TTL_HOURS", "12"))
EMAIL_VERIFICATION_TTL_HOURS = int(env("EMAIL_VERIFICATION_TTL_HOURS", "24"))
HMAC_TIMESTAMP_WINDOW_SECONDS = 300
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json-ish": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json-ish"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# TRON node endpoints per network slug (TronGrid-style HTTP API).
TRON_API_ENDPOINTS: dict[str, list[str]] = {}
TRON_API_KEY = ""

# Solana RPC endpoints per network slug.
SOLANA_RPC_ENDPOINTS: dict[str, list[str]] = {}

# TON (toncenter) endpoints per network slug + optional API key.
TON_API_ENDPOINTS: dict[str, list[str]] = {}
TON_API_KEY = ""
