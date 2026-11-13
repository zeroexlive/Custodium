from __future__ import annotations

import hashlib
import secrets as _secrets

import pyotp
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.utils import timezone
from ninja import Router, Status
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth
from waas.modules.audit.models import AuditEvent
from waas.modules.identity.api.schemas import (
    AuthOut,
    DetailOut,
    LoginIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    TokenIn,
    TotpCodeIn,
    TotpVerifyIn,
    UserOut,
    user_out,
)
from waas.modules.identity.models import DashboardToken, OneTimeToken, User
from waas.security.secret_management.crypto import decrypt_secret, encrypt_secret

router = Router(tags=["identity"])
dashboard_auth = DashboardAuth()

_MFA_SALT = "custodium.totp.challenge"
_MFA_MAX_AGE_SECONDS = 300


def _totp_for(user: User) -> pyotp.TOTP | None:
    if not user.totp_secret_ciphertext:
        return None
    return pyotp.TOTP(decrypt_secret(user.totp_secret_ciphertext))


def _recovery_digest(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").strip().upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _check_totp_or_recovery(user: User, code: str) -> bool:
    """Verify a TOTP code, or consume a one-time recovery code."""
    cleaned = (code or "").strip()
    totp = _totp_for(user)
    if totp is not None and cleaned.isdigit() and totp.verify(cleaned, valid_window=1):
        return True
    digest = _recovery_digest(cleaned)
    hashes = list(user.totp_recovery_hashes or [])
    if digest in hashes:
        hashes.remove(digest)
        user.totp_recovery_hashes = hashes
        user.save(update_fields=["totp_recovery_hashes"])
        return True
    return False


def _issue_session(user: User) -> dict:
    _, raw = DashboardToken.issue(user)
    return {"access_token": raw, "token": raw, "user": user_out(user)}


@router.post("/auth/register", response={201: AuthOut}, auth=None)
def register(request, payload: RegisterIn):
    email = payload.email.strip().lower()
    if User.objects.filter(email=email).exists():
        raise HttpError(409, "Email already registered")
    user = User(email=email, display_name=payload.display_name or "")
    try:
        validate_password(payload.password, user=user)
    except ValidationError as exc:
        raise HttpError(422, "; ".join(exc.messages)) from exc
    user.set_password(payload.password)
    user.save()
    _, verification_raw = OneTimeToken.issue(
        user, OneTimeToken.Purpose.EMAIL_VERIFICATION, settings.EMAIL_VERIFICATION_TTL_HOURS
    )
    AuditEvent.record("user.registered", actor_user=user)
    result = _issue_session(user)
    if getattr(settings, "EXPOSE_TOKEN_IN_RESPONSE", False):
        result["verification_token"] = verification_raw
    return Status(201, result)


@router.post("/auth/login", response=AuthOut, auth=None)
def login(request, payload: LoginIn):
    user = authenticate(request, username=payload.email.strip().lower(), password=payload.password)
    if user is None:
        raise HttpError(401, "Invalid email or password")
    if user.totp_enabled:
        # Password verified; pause at the two-factor challenge.
        # The mfa_token is a signed, 5-minute, single-purpose
        # handle — it is NOT a session token.
        challenge = signing.TimestampSigner(salt=_MFA_SALT).sign_object(
            {"uid": str(user.id)}
        )
        return {
            "access_token": None,
            "token": None,
            "user": user_out(user),
            "requires_totp": True,
            "mfa_token": challenge,
        }
    AuditEvent.record("user.logged_in", actor_user=user)
    return _issue_session(user)


@router.post("/auth/2fa/verify", response=AuthOut, auth=None)
def verify_totp(request, payload: TotpVerifyIn):
    """Complete a login paused at the two-factor challenge."""
    try:
        data = signing.TimestampSigner(salt=_MFA_SALT).unsign_object(
            payload.mfa_token, max_age=_MFA_MAX_AGE_SECONDS
        )
    except signing.BadSignature as exc:
        raise HttpError(401, "Invalid or expired two-factor challenge") from exc
    user = User.objects.filter(id=data.get("uid"), is_active=True).first()
    if user is None or not user.totp_enabled:
        raise HttpError(401, "Invalid or expired two-factor challenge")
    if not _check_totp_or_recovery(user, payload.code):
        raise HttpError(401, "Invalid two-factor code")
    AuditEvent.record("user.logged_in", actor_user=user, metadata={"totp": True})
    return _issue_session(user)


@router.post("/auth/2fa/setup", response=dict, auth=dashboard_auth)
def totp_setup(request):
    """Start TOTP enrollment: returns the shared secret ONCE (plus
    its otpauth:// URI). Nothing is enabled until /auth/2fa/enable
    proves possession with a valid code."""
    user = request.auth
    if user.totp_enabled:
        raise HttpError(409, "Two-factor authentication is already enabled; disable it first")
    secret = pyotp.random_base32()
    user.totp_secret_ciphertext = encrypt_secret(secret)
    user.save(update_fields=["totp_secret_ciphertext"])
    return {
        "secret": secret,
        "provisioning_uri": pyotp.TOTP(secret).provisioning_uri(
            name=user.email, issuer_name="Custodium"
        ),
        "enabled": False,
    }


@router.post("/auth/2fa/enable", response=dict, auth=dashboard_auth)
def totp_enable(request, payload: TotpCodeIn):
    user = request.auth
    if user.totp_enabled:
        raise HttpError(409, "Two-factor authentication is already enabled")
    totp = _totp_for(user)
    if totp is None:
        raise HttpError(409, "Run /auth/2fa/setup first")
    if not totp.verify(payload.code.strip(), valid_window=1):
        raise HttpError(422, "Invalid two-factor code")
    codes = [
        f"{_secrets.token_hex(2).upper()}-{_secrets.token_hex(2).upper()}"
        for _ in range(8)
    ]
    user.totp_enabled = True
    user.totp_recovery_hashes = [_recovery_digest(c) for c in codes]
    user.save(update_fields=["totp_enabled", "totp_recovery_hashes"])
    AuditEvent.record("user.totp_enabled", actor_user=user)
    # Recovery codes are shown exactly once; only digests are kept.
    return {"enabled": True, "recovery_codes": codes}


@router.post("/auth/2fa/disable", response=dict, auth=dashboard_auth)
def totp_disable(request, payload: TotpCodeIn):
    user = request.auth
    if not user.totp_enabled:
        raise HttpError(409, "Two-factor authentication is not enabled")
    if not _check_totp_or_recovery(user, payload.code):
        raise HttpError(422, "Invalid two-factor code")
    user.totp_enabled = False
    user.totp_secret_ciphertext = None
    user.totp_recovery_hashes = []
    user.save(
        update_fields=["totp_enabled", "totp_secret_ciphertext", "totp_recovery_hashes"]
    )
    AuditEvent.record("user.totp_disabled", actor_user=user)
    return {"enabled": False}


@router.post("/auth/logout", response=DetailOut, auth=dashboard_auth)
def logout(request):
    token = DashboardToken.objects.filter(user=request.auth).exclude(revoked_at__isnull=False)
    raw = getattr(request, "dashboard_token", None)
    if raw:
        import hashlib

        token = token.filter(token_hash=hashlib.sha256(raw.encode()).hexdigest())
    for entry in token:
        entry.revoke()
    return {"detail": "Logged out"}


@router.get("/me", response=UserOut, auth=dashboard_auth)
def me(request):
    return user_out(request.auth)


@router.post("/auth/verify-email", response=DetailOut, auth=None)
def verify_email(request, payload: TokenIn):
    user = OneTimeToken.consume(payload.token, OneTimeToken.Purpose.EMAIL_VERIFICATION)
    if user is None:
        raise HttpError(400, "Invalid or expired verification token")
    user.is_email_verified = True
    user.save(update_fields=["is_email_verified"])
    AuditEvent.record("user.email_verified", actor_user=user)
    return {"detail": "Email verified"}


@router.post("/auth/password-reset/request", response=DetailOut, auth=None)
def password_reset_request(request, payload: PasswordResetRequestIn):
    # Generic response either way: never reveal whether an account exists.
    result: dict = {"detail": "If an account exists for that email, a reset link has been issued."}
    user = User.objects.filter(email=payload.email.strip().lower()).first()
    if user is not None:
        _, raw = OneTimeToken.issue(user, OneTimeToken.Purpose.PASSWORD_RESET, 2)
        AuditEvent.record("user.password_reset_requested", actor_user=user)
        if getattr(settings, "EXPOSE_TOKEN_IN_RESPONSE", False):
            result["reset_token"] = raw
    return result


@router.post("/auth/password-reset/confirm", response=DetailOut, auth=None)
def password_reset_confirm(request, payload: PasswordResetConfirmIn):
    user = OneTimeToken.consume(payload.token, OneTimeToken.Purpose.PASSWORD_RESET)
    if user is None:
        raise HttpError(400, "Invalid or expired reset token")
    try:
        validate_password(payload.new_password, user=user)
    except ValidationError as exc:
        raise HttpError(422, "; ".join(exc.messages)) from exc
    user.set_password(payload.new_password)
    user.save(update_fields=["password"])
    DashboardToken.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
    AuditEvent.record("user.password_reset_completed", actor_user=user)
    return {"detail": "Password updated"}
