from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from control_api import Auth0Configuration, Auth0PrincipalResolver


TENANT_CLAIM = "https://app.secure-db-access-gateway.org/tenant_id"


@dataclass
class SigningKey:
    key: object


class StaticJwksClient:
    def __init__(self, key: object):
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> SigningKey:
        return SigningKey(self.key)


@pytest.fixture
def resolver():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    configuration = Auth0Configuration(
        domain="tenant.example.auth0.com",
        audience="https://api.example.com",
    )
    return (
        Auth0PrincipalResolver(
            configuration,
            jwks_client=StaticJwksClient(private_key.public_key()),
        ),
        private_key,
        configuration,
    )


def make_token(private_key, configuration, **claims):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "auth0|user-1",
        TENANT_CLAIM: "org-a",
        "iss": configuration.issuer_url,
        "aud": configuration.audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_resolves_principal_from_valid_token_and_ignores_client_tenant_header(resolver):
    auth, private_key, configuration = resolver

    principal = auth.resolve(
        {
            "HTTP_AUTHORIZATION": f"Bearer {make_token(private_key, configuration)}",
            "HTTP_X_TENANT_ID": "org-attacker",
        }
    )

    assert principal.user_id == "auth0|user-1"
    assert principal.org_id == "org-a"


def test_rejects_invalid_token(resolver):
    auth, _, _ = resolver

    with pytest.raises(PermissionError, match="Authentication required"):
        auth.resolve({"HTTP_AUTHORIZATION": "Bearer not-a-jwt"})


def test_rejects_token_without_tenant_claim(resolver):
    auth, private_key, configuration = resolver
    token = make_token(private_key, configuration, **{TENANT_CLAIM: ""})

    with pytest.raises(PermissionError, match="Authentication required"):
        auth.resolve({"HTTP_AUTHORIZATION": f"Bearer {token}"})


def test_rejects_token_with_wrong_audience(resolver):
    auth, private_key, configuration = resolver
    token = make_token(private_key, configuration, aud="https://other.example.com")

    with pytest.raises(PermissionError, match="Authentication required"):
        auth.resolve({"HTTP_AUTHORIZATION": f"Bearer {token}"})
