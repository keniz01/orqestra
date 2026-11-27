"""Auth0 bearer-token validation and trusted principal construction."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from execution_kernel import Principal


DEFAULT_TENANT_CLAIM = "https://app.secure-db-access-gateway.org/tenant_id"
DEFAULT_ROLES_CLAIM = "https://app.read-only-database-explorer.org/roles"


class SigningKeyClient(Protocol):
    """Resolve the signing key for a JWT, normally from Auth0 JWKS."""

    def get_signing_key_from_jwt(self, token: str) -> Any:
        """Return an object with the public key in its ``key`` attribute."""


@dataclass(frozen=True, slots=True)
class Auth0Configuration:
    """Validated configuration for one Auth0 API audience and issuer."""

    domain: str
    audience: str
    issuer: str | None = None
    tenant_claim: str = DEFAULT_TENANT_CLAIM
    roles_claim: str = DEFAULT_ROLES_CLAIM

    def __post_init__(self) -> None:
        for field_name in ("domain", "audience", "tenant_claim", "roles_claim"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.issuer is not None and not self.issuer.strip():
            raise ValueError("issuer must be non-empty when provided")

    @property
    def issuer_url(self) -> str:
        return (self.issuer or f"https://{self.domain}/").rstrip("/") + "/"

    @property
    def jwks_url(self) -> str:
        return f"https://{self.domain}/.well-known/jwks.json"

    @classmethod
    def from_environment(cls) -> Auth0Configuration:
        """Load production configuration without accepting request metadata."""

        domain = os.getenv("AUTH0_DOMAIN", "").strip()
        audience = (
            os.getenv("AUTH0_AUDIENCE", "").strip()
            or os.getenv("AUTH0_API_AUDIENCE", "").strip()
        )
        if not domain or not audience:
            raise ValueError("AUTH0_DOMAIN and AUTH0_AUDIENCE are required.")
        return cls(
            domain=domain,
            audience=audience,
            issuer=os.getenv("AUTH0_ISSUER") or None,
            tenant_claim=os.getenv("AUTH0_TENANT_CLAIM", DEFAULT_TENANT_CLAIM),
            roles_claim=os.getenv("AUTH0_ROLES_CLAIM", DEFAULT_ROLES_CLAIM),
        )


class Auth0PrincipalResolver:
    """Resolve a principal only from a server-validated Auth0 access token."""

    def __init__(
        self,
        configuration: Auth0Configuration,
        *,
        jwks_client: SigningKeyClient | None = None,
        leeway_seconds: int = 2,
    ) -> None:
        if leeway_seconds < 0:
            raise ValueError("leeway_seconds must not be negative")
        self._configuration = configuration
        self._jwks_client = jwks_client or PyJWKClient(configuration.jwks_url, cache_keys=True)
        self._leeway_seconds = leeway_seconds

    def resolve(self, environ: dict[str, object]) -> Principal:
        """Validate the bearer token and map its claims to the trusted contract."""

        token = _extract_bearer_token(environ.get("HTTP_AUTHORIZATION"))
        if token is None:
            raise PermissionError("Authentication required.")

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=self._configuration.audience,
                issuer=self._configuration.issuer_url,
                leeway=self._leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except (PyJWTError, TypeError, ValueError) as exc:
            raise PermissionError("Authentication required.") from exc

        principal = _principal_from_claims(claims, self._configuration)
        if principal is None:
            raise PermissionError("Authentication required.")
        return principal


def _extract_bearer_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    scheme, separator, token = value.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def _principal_from_claims(
    claims: Mapping[str, Any],
    configuration: Auth0Configuration,
) -> Principal | None:
    user_id = claims.get("sub")
    org_id = claims.get(configuration.tenant_claim)
    if not all(isinstance(value, str) and value.strip() for value in (user_id, org_id)):
        return None

    roles = claims.get("roles") or claims.get(configuration.roles_claim) or []
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, (list, tuple, set, frozenset)):
        return None
    normalized_roles = frozenset(
        role.strip().lower()
        for role in roles
        if isinstance(role, str) and role.strip()
    )
    attributes = {
        str(key): value
        for key, value in claims.items()
        if key not in {"sub", "roles", configuration.tenant_claim, configuration.roles_claim}
    }
    return Principal(user_id=user_id, org_id=org_id, roles=normalized_roles, attributes=attributes)
