from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra: object) -> User:
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra: object) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_email_verified", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Customer user. Email is the identity; dashboard auth is separate from machine API auth."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=150, blank=True)
    is_email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "identity_user"

    def __str__(self) -> str:
        return self.email


class DashboardToken(models.Model):
    """Revocable dashboard bearer token. Only the SHA-256 hash is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dashboard_tokens")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_dashboard_token"

    @classmethod
    def issue(cls, user: User) -> tuple[DashboardToken, str]:
        raw = secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user,
            token_hash=_hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=settings.DASHBOARD_TOKEN_TTL_HOURS),
        )
        return token, raw

    @classmethod
    def resolve(cls, raw: str) -> User | None:
        try:
            token = cls.objects.select_related("user").get(token_hash=_hash_token(raw))
        except cls.DoesNotExist:
            return None
        if token.revoked_at is not None or token.expires_at <= timezone.now() or not token.user.is_active:
            return None
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token.user

    def revoke(self) -> None:
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])


class OneTimeToken(models.Model):
    """Hashed one-time tokens for email verification and password reset."""

    class Purpose(models.TextChoices):
        EMAIL_VERIFICATION = "email_verification", "Email verification"
        PASSWORD_RESET = "password_reset", "Password reset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="one_time_tokens")
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "identity_one_time_token"
        constraints = [
            models.UniqueConstraint(fields=["purpose", "token_hash"], name="uniq_one_time_token_purpose_hash")
        ]

    @classmethod
    def issue(cls, user: User, purpose: str, ttl_hours: int) -> tuple[OneTimeToken, str]:
        raw = secrets.token_urlsafe(32)
        cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=timezone.now())
        token = cls.objects.create(
            user=user, purpose=purpose, token_hash=_hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=ttl_hours),
        )
        return token, raw

    @classmethod
    def consume(cls, raw: str, purpose: str) -> User | None:
        try:
            token = cls.objects.select_related("user").get(purpose=purpose, token_hash=_hash_token(raw))
        except cls.DoesNotExist:
            return None
        if token.used_at is not None or token.expires_at <= timezone.now():
            return None
        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])
        return token.user
