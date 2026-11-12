from .base import *  # noqa: F401,F403

DEBUG = False
EXPOSE_TOKEN_IN_RESPONSE = True  # tests need verification/reset tokens
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
