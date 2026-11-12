from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
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
    UserOut,
    user_out,
)
from waas.modules.identity.models import DashboardToken, OneTimeToken, User

router = Router(tags=["identity"])
dashboard_auth = DashboardAuth()


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
    AuditEvent.record("user.logged_in", actor_user=user)
    return _issue_session(user)


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
