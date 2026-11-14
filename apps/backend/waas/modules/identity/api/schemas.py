from __future__ import annotations

from ninja import Schema


class CustomerCreateIn(Schema):
    """Platform-admin customer creation. There is NO public
    registration: accounts are created only by the platform owner /
    global administrators, who receive the generated temporary
    password once and deliver it to the customer."""

    email: str
    display_name: str | None = ""


class LoginIn(Schema):
    email: str
    password: str


class UserOut(Schema):
    id: str
    email: str
    display_name: str = ""
    is_email_verified: bool = False
    totp_enabled: bool = False
    is_staff: bool = False
    is_superuser: bool = False


class TotpCodeIn(Schema):
    code: str


class TotpVerifyIn(Schema):
    mfa_token: str
    code: str


class AuthOut(Schema):
    # token/access_token are null exactly when requires_totp is
    # true: the login is paused at the two-factor challenge and
    # completes via POST /auth/2fa/verify.
    access_token: str | None = None
    token: str | None = None
    requires_totp: bool = False
    mfa_token: str | None = None
    user: UserOut


class TokenIn(Schema):
    token: str


class PasswordResetRequestIn(Schema):
    email: str


class PasswordResetConfirmIn(Schema):
    token: str
    new_password: str


class DetailOut(Schema):
    detail: str
    reset_token: str | None = None


def user_out(user: object) -> dict:
    return {
        "id": str(user.id),  # type: ignore[attr-defined]
        "email": user.email,  # type: ignore[attr-defined]
        "display_name": user.display_name or "",  # type: ignore[attr-defined]
        "is_email_verified": bool(user.is_email_verified),  # type: ignore[attr-defined]
        "totp_enabled": bool(user.totp_enabled),  # type: ignore[attr-defined]
        "is_staff": bool(getattr(user, "is_staff", False)),  # type: ignore[attr-defined]
        "is_superuser": bool(getattr(user, "is_superuser", False)),  # type: ignore[attr-defined]
    }
