from __future__ import annotations

from ninja import Schema


class RegisterIn(Schema):
    email: str
    password: str
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
    # Present only in development/testing settings (EXPOSE_TOKEN_IN_RESPONSE),
    # so the verification flow can be exercised without a mail server.
    verification_token: str | None = None


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
    }
