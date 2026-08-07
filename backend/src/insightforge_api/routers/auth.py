"""Authentication & identity: registration + email verification, login with
MFA step-up (428), refresh-token rotation, logout, password reset/change,
profile, invitation acceptance. Tenant context always derives from the
authenticated token — never from a client-supplied field."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy import text as sqltext
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..config import REFRESH_TOKEN_DAYS
from ..db import bootstrap_session, session_factory, tenant_scoped_session, user_scoped_session
from ..deps import TenantContext, get_context, get_session
from ..models import Invitation, Membership, RefreshToken, Tenant, User, Workspace
from ..roles import ROLES, TENANT_OWNER
from ..security import (
    decode_access_token,
    hash_password,
    issue_access_token,
    new_opaque_token,
    new_totp_secret,
    sha256_of,
    totp_verify,
    verify_password,
)
from ..services import mailer

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterIn(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=255)
    tenant_slug: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*$")
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    tenant_id: str
    tenant_slug: str
    role: str
    user_id: str
    display_name: str
    email_verified: bool
    onboarding: dict


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    otp: str | None = None
    tenant_slug: str | None = None


async def _issue_pair(session, user: User, tenant: Tenant, role: str) -> TokenOut:
    raw, token_hash = new_opaque_token()
    session.add(RefreshToken(
        user_id=user.id, token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)))
    return TokenOut(
        access_token=issue_access_token(user.id, tenant.id, role), refresh_token=raw,
        tenant_id=str(tenant.id), tenant_slug=tenant.slug, role=role, user_id=str(user.id),
        display_name=user.display_name, email_verified=user.email_verified,
        onboarding={"plan": tenant.plan_code},
    )


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, request: Request):
    tenant = Tenant(slug=body.tenant_slug, name=body.tenant_name)
    verify_raw, verify_hash = new_opaque_token()
    async with bootstrap_session(tenant.id) as s:
        await s.execute(sqltext("SELECT set_config('app.login_email', :e, true)"),
                        {"e": body.email.lower()})
        existing = (await s.execute(
            select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(409, "An account with this email already exists — log in instead")
        s.add(tenant)
        user = User(email=body.email.lower(), display_name=body.display_name,
                    password_hash=hash_password(body.password), email_verify_hash=verify_hash)
        s.add(user)
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(
                409, f"The workspace URL '{body.tenant_slug}' is taken — pick another slug"
            ) from None
        s.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TENANT_OWNER))
        s.add(Workspace(tenant_id=tenant.id, name="Main workspace", created_by=user.id))
        await mailer.send(
            s, tenant_id=tenant.id, to_email=user.email, kind="verify_email",
            subject="Verify your InsightForge email",
            body=f"Welcome to InsightForge, {user.display_name}.\n\n"
                 f"Confirm this address with token:\n\n{verify_raw}\n\n"
                 f"POST /api/v1/auth/verify-email {{\"token\": \"...\"}} or paste it in "
                 f"Settings -> Verify email.")
        await audit.record(s, tenant_id=tenant.id, actor_user_id=user.id,
                           action="tenant.registered", resource_type="tenant",
                           resource_id=str(tenant.id),
                           correlation_id=getattr(request.state, "correlation_id", ""))
        return await _issue_pair(s, user, tenant, TENANT_OWNER)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request):
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext("SELECT set_config('app.login_email', :e, true)"),
                            {"e": body.email.lower()})
            user = (await s.execute(
                select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    if user.mfa_enabled:
        if not body.otp:
            raise HTTPException(428, "MFA code required")
        if not totp_verify(user.mfa_secret or "", body.otp):
            raise HTTPException(401, "MFA code is incorrect")
    async with user_scoped_session(user.id) as s:
        memberships = (await s.execute(
            select(Membership).where(Membership.user_id == user.id))).scalars().all()
        if not memberships:
            raise HTTPException(403, "This account belongs to no organization")
        chosen = memberships[0]
        if body.tenant_slug:
            tenants = (await s.execute(select(Tenant))).scalars().all()
            match = next((t for t in tenants if t.slug == body.tenant_slug), None)
            if match is None:
                raise HTTPException(401, "No membership in that organization")
            chosen = next(m for m in memberships if m.tenant_id == match.id)
        tenant = (await s.execute(
            select(Tenant).where(Tenant.id == chosen.tenant_id))).scalar_one()
        if tenant.status != "active":
            raise HTTPException(403, "This organization is suspended — contact support")
    async with tenant_scoped_session(tenant.id) as s:
        merged_user = await s.merge(user)
        out = await _issue_pair(s, merged_user, tenant, chosen.role)
        await audit.record(s, tenant_id=tenant.id, actor_user_id=user.id,
                           action="user.login", resource_type="user", resource_id=str(user.id),
                           correlation_id=getattr(request.state, "correlation_id", ""))
        return out


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn):
    token_hash = sha256_of(body.refresh_token)
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext(
                "SELECT set_config('app.refresh_token_hash', :h, true)"), {"h": token_hash})
            rt = (await s.execute(select(RefreshToken).where(
                RefreshToken.token_hash == token_hash))).scalar_one_or_none()
            if rt is None or rt.revoked or rt.expires_at < datetime.now(timezone.utc):
                raise HTTPException(401, "Session expired — log in again")
            rt.revoked = True  # rotation: each refresh token is single-use
            await s.execute(sqltext("SELECT set_config('app.user_id', :u, true)"),
                            {"u": str(rt.user_id)})
            user = (await s.execute(select(User).where(User.id == rt.user_id))).scalar_one()
    async with user_scoped_session(user.id) as s:
        membership = (await s.execute(select(Membership).where(
            Membership.user_id == user.id))).scalars().first()
        if membership is None:
            raise HTTPException(403, "This account belongs to no organization")
        tenant = (await s.execute(
            select(Tenant).where(Tenant.id == membership.tenant_id))).scalar_one()
    async with tenant_scoped_session(tenant.id) as s:
        merged = await s.merge(user)
        return await _issue_pair(s, merged, tenant, membership.role)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, ctx: TenantContext = Depends(get_context)):
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext(
                "SELECT set_config('app.refresh_token_hash', :h, true)"),
                {"h": sha256_of(body.refresh_token)})
            rt = (await s.execute(select(RefreshToken).where(
                RefreshToken.token_hash == sha256_of(body.refresh_token)))).scalar_one_or_none()
            if rt is not None and rt.user_id == ctx.user_id:
                rt.revoked = True


class VerifyIn(BaseModel):
    token: str


@router.post("/verify-email")
async def verify_email(body: VerifyIn, ctx: TenantContext = Depends(get_context),
                       session=Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if user.email_verified:
        return {"email_verified": True}
    if not user.email_verify_hash or sha256_of(body.token) != user.email_verify_hash:
        raise HTTPException(400, "Verification token is invalid")
    user.email_verified = True
    user.email_verify_hash = None
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="user.email_verified", resource_type="user",
                       resource_id=str(ctx.user_id))
    await session.commit()  # persist before responding (teardown commit runs post-response)
    return {"email_verified": True}


class ResetRequestIn(BaseModel):
    email: EmailStr


@router.post("/password-reset/request", status_code=202)
async def password_reset_request(body: ResetRequestIn):
    """Always 202 — never reveals whether the address exists."""
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext("SELECT set_config('app.login_email', :e, true)"),
                            {"e": body.email.lower()})
            user = (await s.execute(
                select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
            if user is None:
                return {"status": "accepted"}
            raw, token_hash = new_opaque_token()
            user.reset_hash = token_hash
            user.reset_expires = datetime.now(timezone.utc) + timedelta(hours=2)
            membership = (await s.execute(select(Membership).where(
                Membership.user_id == user.id))).scalars().first()
            tenant_id = membership.tenant_id if membership else user.id
            await s.execute(  # arm tenant GUC so the outbox row passes RLS
                sqltext("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(tenant_id)})
            await mailer.send(
                s, tenant_id=tenant_id, to_email=user.email, kind="password_reset",
                subject="Reset your InsightForge password",
                body=f"A password reset was requested for this address.\n\nToken:\n{raw}\n\n"
                     f"POST /api/v1/auth/password-reset/confirm with this token and a new "
                     f"password. The token expires in 2 hours. If you did not request this, "
                     f"ignore this email.")
    return {"status": "accepted"}


class ResetConfirmIn(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=128)


@router.post("/password-reset/confirm")
async def password_reset_confirm(body: ResetConfirmIn):
    token_hash = sha256_of(body.token)
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext("SELECT set_config('app.reset_hash', :h, true)"),
                            {"h": token_hash})
            user = (await s.execute(
                select(User).where(User.reset_hash == token_hash))).scalar_one_or_none()
            if (user is None or user.reset_expires is None
                    or user.reset_expires < datetime.now(timezone.utc)):
                raise HTTPException(400, "Reset token is invalid or expired — request a new one")
            await s.execute(sqltext("SELECT set_config('app.user_id', :u, true)"),
                            {"u": str(user.id)})
            user.password_hash = hash_password(body.new_password)
            user.reset_hash = None
            user.reset_expires = None
            # Revoke every refresh token: a reset invalidates all sessions.
            for rt in (await s.execute(select(RefreshToken).where(
                    RefreshToken.user_id == user.id))).scalars():
                rt.revoked = True
    return {"status": "password_updated"}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


@router.post("/password/change")
async def change_password(body: ChangePasswordIn, ctx: TenantContext = Depends(get_context),
                          session=Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="user.password_changed", resource_type="user",
                       resource_id=str(ctx.user_id))
    await session.commit()  # persist before responding (teardown commit runs post-response)
    return {"status": "password_updated"}


class ProfileOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    tenant_id: str
    mfa_enabled: bool
    email_verified: bool


@router.get("/me", response_model=ProfileOut)
async def me(ctx: TenantContext = Depends(get_context), session=Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    return ProfileOut(user_id=str(user.id), email=user.email, display_name=user.display_name,
                      role=ctx.role, tenant_id=str(ctx.tenant_id),
                      mfa_enabled=user.mfa_enabled, email_verified=user.email_verified)


class ProfilePatch(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)


@router.patch("/me", response_model=ProfileOut)
async def update_me(body: ProfilePatch, ctx: TenantContext = Depends(get_context),
                    session=Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    user.display_name = body.display_name
    await session.commit()  # persist before responding (teardown commit runs post-response)
    return ProfileOut(user_id=str(user.id), email=user.email, display_name=user.display_name,
                      role=ctx.role, tenant_id=str(ctx.tenant_id),
                      mfa_enabled=user.mfa_enabled, email_verified=user.email_verified)


@router.post("/mfa/setup")
async def mfa_setup(ctx: TenantContext = Depends(get_context), session=Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")
    secret = new_totp_secret()
    user.mfa_secret = secret
    uri = (f"otpauth://totp/InsightForge:{user.email}?secret={secret}&issuer=InsightForge")
    await session.commit()  # persist the MFA secret before responding
    return {"secret": secret, "otpauth_uri": uri}


class MfaEnableIn(BaseModel):
    otp: str


@router.post("/mfa/enable")
async def mfa_enable(body: MfaEnableIn, ctx: TenantContext = Depends(get_context),
                     session=Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if not user.mfa_secret or not totp_verify(user.mfa_secret, body.otp):
        raise HTTPException(400, "MFA code is incorrect — scan the secret and try again")
    user.mfa_enabled = True
    await audit.record(session, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
                       action="user.mfa_enabled", resource_type="user",
                       resource_id=str(ctx.user_id))
    await session.commit()  # persist before responding (teardown commit runs post-response)
    return {"mfa_enabled": True}


class AcceptInviteIn(BaseModel):
    token: str
    password: str | None = Field(default=None, min_length=10, max_length=128)
    display_name: str | None = None


@router.post("/invitations/accept", response_model=TokenOut)
async def accept_invitation(body: AcceptInviteIn):
    token_hash = sha256_of(body.token)
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext("SELECT set_config('app.invite_token_hash', :h, true)"),
                            {"h": token_hash})
            invite = (await s.execute(select(Invitation).where(
                Invitation.token_hash == token_hash))).scalar_one_or_none()
            if invite is None or invite.accepted:
                raise HTTPException(400, "Invitation is invalid or already used")
            if invite.expires_at < datetime.now(timezone.utc):
                raise HTTPException(400, "Invitation has expired — ask for a new one")
            invite_tenant_id, invite_email, invite_role = (
                invite.tenant_id, invite.email, invite.role)
    async with session_factory()() as s:
        async with s.begin():
            await s.execute(sqltext("SELECT set_config('app.login_email', :e, true)"),
                            {"e": invite_email.lower()})
            user = (await s.execute(
                select(User).where(User.email == invite_email.lower()))).scalar_one_or_none()
            if user is None:
                if not body.password:
                    raise HTTPException(400, "Set a password (10+ characters) to join")
                user = User(email=invite_email.lower(),
                            display_name=body.display_name or invite_email.split("@")[0],
                            password_hash=hash_password(body.password), email_verified=True)
                s.add(user)
                await s.flush()
            user_id = user.id
    async with tenant_scoped_session(invite_tenant_id) as s:
        await s.execute(sqltext("SELECT set_config('app.invite_token_hash', :h, true)"),
                        {"h": token_hash})
        invite = (await s.execute(select(Invitation).where(
            Invitation.token_hash == token_hash))).scalar_one()
        existing = (await s.execute(select(Membership).where(
            Membership.tenant_id == invite_tenant_id,
            Membership.user_id == user_id))).scalar_one_or_none()
        if existing is None:
            s.add(Membership(tenant_id=invite_tenant_id, user_id=user_id, role=invite_role))
        invite.accepted = True
        tenant = (await s.execute(
            select(Tenant).where(Tenant.id == invite_tenant_id))).scalar_one()
        user = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
        await audit.record(s, tenant_id=invite_tenant_id, actor_user_id=user_id,
                           action="member.joined", resource_type="membership")
        return await _issue_pair(s, user, tenant, invite_role)


def _validate_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(ROLES)}")
    return role


def _uuid_or_422(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(422, f"{label} must be a valid UUID") from None


__all__ = ["router", "decode_access_token", "_validate_role", "_uuid_or_422"]
