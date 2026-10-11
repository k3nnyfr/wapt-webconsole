"""User authentication: OpenID Connect (Authelia or any provider), session cookie, roles and CSRF.

Backend-for-Frontend: the browser never sees a token. After the authorization code flow (with PKCE) the backend
keeps only the user identity and role in a signed session cookie (HttpOnly, Secure behind HTTPS).

The cookie is ``SameSite=Lax``, not ``Strict``: the provider redirects back to ``/auth/callback`` from another
site, and a Strict cookie would be dropped there (state check fails). Requests that change state are protected
by a CSRF token instead, sent by the frontend in the ``X-CSRF-Token`` header.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Annotated

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import Settings, role_at_least, role_for_groups

log = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

router = APIRouter(prefix="/auth", tags=["auth"])


class User(BaseModel):
    sub: str
    username: str
    name: str = ""
    email: str = ""
    groups: list[str] = []
    role: str
    login_at: float


def make_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    if settings.oidc_issuer:
        oauth.register(
            "oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": settings.oidc_scopes, "code_challenge_method": "S256"},
        )
    return oauth


def safe_next(target: str | None) -> str:
    """Only local paths after login: no open redirect to another site."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


@router.get("/login")
async def login(request: Request, next: str = "/"):
    oauth: OAuth = request.app.state.oauth
    if oauth.create_client("oidc") is None:
        raise HTTPException(503, "OpenID Connect is not configured (WWC_OIDC_ISSUER)")
    settings: Settings = request.app.state.settings
    request.session.clear()
    request.session["next"] = safe_next(next)
    return await oauth.oidc.authorize_redirect(request, settings.public_url.rstrip("/") + "/auth/callback")


@router.get("/callback")
async def callback(request: Request):
    settings: Settings = request.app.state.settings
    oauth: OAuth = request.app.state.oauth
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except OAuthError as e:
        log.warning("OIDC callback refused: %s", e.error)
        return RedirectResponse("/?auth_error=callback", status_code=303)
    claims = dict(token.get("userinfo") or {})
    # Authelia returns groups from the userinfo endpoint (not always in the ID token)
    if "groups" not in claims:
        claims.update(await oauth.oidc.userinfo(token=token))
    groups = list(claims.get("groups") or [])
    username = claims.get("preferred_username") or claims.get("sub", "")
    role = role_for_groups(groups, settings.role_groups)
    target = request.session.get("next", "/")
    request.session.clear()
    if role is None:
        log.warning("Login refused for %s: none of the groups %s grants a role", username, groups)
        return RedirectResponse("/?auth_error=forbidden", status_code=303)
    user = User(sub=claims["sub"], username=username, name=claims.get("name", ""), email=claims.get("email", ""),
                groups=groups, role=role, login_at=time.time())
    request.session["user"] = user.model_dump()
    request.session["csrf"] = secrets.token_urlsafe(32)
    log.info("Login of %s (%s)", username, role)
    return RedirectResponse(target, status_code=303)


def current_user(request: Request) -> User:
    data = request.session.get("user")
    if not data:
        raise HTTPException(401, "not authenticated")
    user = User(**data)
    settings: Settings = request.app.state.settings
    if time.time() - user.login_at > settings.session_max_age:     # absolute lifetime, even if the cookie slides
        request.session.clear()
        raise HTTPException(401, "session expired")
    return user


def check_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    expected = request.session.get("csrf")
    sent = request.headers.get("X-CSRF-Token", "")
    if not expected or not secrets.compare_digest(expected, sent):
        raise HTTPException(403, "missing or invalid CSRF token")


def require(role: str):
    """Dependency: authenticated user with at least ``role``; CSRF checked on requests that change state."""

    def dependency(request: Request) -> User:
        user = current_user(request)
        if not role_at_least(user.role, role):
            raise HTTPException(403, f"the {role} role is required")
        check_csrf(request)
        return user

    return dependency


@router.post("/logout")
async def logout(request: Request, user: Annotated[User, Depends(require("viewer"))]):
    request.session.clear()
    log.info("Logout of %s", user.username)
    return {"ok": True}
