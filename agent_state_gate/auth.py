"""OIDC authentication and tenant context construction."""

from __future__ import annotations

import jwt
import requests
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from .config import OIDCConfig, RuntimeProfile
from .models import RequestContext


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


class OIDCAuthenticator:
    def __init__(self, config: OIDCConfig):
        self._config = config
        self._jwk_client: PyJWKClient | None = None

    def _jwks_url(self) -> str:
        if self._config.jwks_url:
            return self._config.jwks_url
        if not self._config.issuer:
            raise AuthenticationError("OIDC issuer is not configured")
        discovery_url = self._config.issuer.rstrip("/") + "/.well-known/openid-configuration"
        try:
            response = requests.get(discovery_url, timeout=5)
            response.raise_for_status()
            jwks_uri = response.json().get("jwks_uri")
        except Exception as exc:
            raise AuthenticationError("OIDC discovery failed") from exc
        if not jwks_uri:
            raise AuthenticationError("OIDC discovery response has no jwks_uri")
        return str(jwks_uri)

    def _client(self) -> PyJWKClient:
        if self._jwk_client is None:
            self._jwk_client = PyJWKClient(
                self._jwks_url(),
                cache_jwk_set=True,
                lifespan=self._config.jwks_cache_seconds,
            )
        return self._jwk_client

    def authenticate(self, token: str) -> RequestContext:
        if not self._config.enabled:
            raise AuthenticationError("OIDC authentication is disabled")
        if not token:
            raise AuthenticationError("Bearer token is required")
        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._config.algorithms,
                audience=self._config.audience,
                issuer=self._config.issuer,
                options={"require": ["exp", self._config.subject_claim, self._config.tenant_claim, self._config.roles_claim]},
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("OIDC token validation failed") from exc
        subject = claims.get(self._config.subject_claim)
        tenant_id = claims.get(self._config.tenant_claim)
        if self._config.roles_claim not in claims:
            raise AuthenticationError("OIDC roles claim is required")
        raw_roles = claims[self._config.roles_claim]
        if subject is None or tenant_id is None:
            raise AuthenticationError("OIDC subject and tenant claims are required")
        if isinstance(raw_roles, str):
            roles = frozenset(role for role in raw_roles.replace(",", " ").split() if role)
        elif isinstance(raw_roles, list):
            roles = frozenset(str(role) for role in raw_roles)
        else:
            raise AuthenticationError("OIDC roles claim must be a string or list")
        return RequestContext(
            tenant_id=str(tenant_id),
            subject=str(subject),
            roles=roles,
            authenticated=True,
        )


def local_request_context(
    *,
    profile: RuntimeProfile,
    tenant_id: str,
    subject: str,
    roles: set[str] | frozenset[str] | None = None,
) -> RequestContext:
    if profile not in {RuntimeProfile.LOCAL_ADVISORY, RuntimeProfile.CI_CONTRACT}:
        raise AuthenticationError("development principal is forbidden outside local/CI profiles")
    return RequestContext(
        tenant_id=tenant_id,
        subject=subject,
        roles=frozenset(roles or set()),
        authenticated=False,
    )


def require_role(context: RequestContext, *allowed_roles: str) -> None:
    if not context.roles.intersection(allowed_roles):
        raise AuthorizationError(f"one of roles {allowed_roles!r} is required")


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "OIDCAuthenticator",
    "local_request_context",
    "require_role",
]
