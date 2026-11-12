from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
# Email verification/reset tokens are returned in API responses ONLY in
# development, so the flows can be exercised without a mail server.
EXPOSE_TOKEN_IN_RESPONSE = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
