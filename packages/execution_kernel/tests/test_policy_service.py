from __future__ import annotations

import time
from datetime import datetime, timezone

from execution_kernel import (
    CapabilityRequest,
    DecisionProvenance,
    PolicyDecisionResponse,
    PolicyServiceAdapter,
    Principal,
    ReferencePolicyServiceAdapter,
)


def make_request(org_id: str = "org-1") -> CapabilityRequest:
    return CapabilityRequest(
        principal=Principal("user-1", org_id, frozenset({"viewer"})),
        capability="data.execute_read_query",
        database_id="analytics",
        tables=("customers",),
        columns=frozenset({"id", "email"}),
    )


def provenance(tenant_id: str = "org-1") -> DecisionProvenance:
    return DecisionProvenance(
        source="test-policy",
        policy_version="test-v1",
        decision_id="decision-1",
        evaluated_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
    )


def test_reference_adapter_allows_and_preserves_decision_provenance():
    adapter = ReferencePolicyServiceAdapter(
        allow_rules=(
            {
                "capability": "data.execute_read_query",
                "org_id": "org-1",
                "roles": ("viewer",),
                "database_id": "analytics",
                "tables": ("customers",),
                "masked_columns": ("email",),
            },
        )
    )

    decision = adapter.evaluate(make_request())

    assert decision.allowed is True
    assert decision.masked_columns == frozenset({"email"})
    assert decision.provenance is not None
    assert decision.provenance.tenant_id == "org-1"
    assert decision.provenance.source == "reference"


def test_reference_adapter_denies_when_no_rule_matches():
    adapter = ReferencePolicyServiceAdapter()

    decision = adapter.evaluate(make_request())

    assert decision.allowed is False
    assert "No allow policy" in decision.reason
    assert decision.provenance is not None


def test_adapter_fails_closed_on_timeout():
    class SlowService:
        def decide(self, request):
            time.sleep(0.2)
            return PolicyDecisionResponse(True, "allowed", provenance())

    adapter = PolicyServiceAdapter(SlowService(), timeout_seconds=0.01)

    decision = adapter.evaluate(make_request())

    assert decision.allowed is False
    assert "timeout" in decision.reason


def test_adapter_fails_closed_when_service_is_unavailable():
    class UnavailableService:
        def decide(self, request):
            raise ConnectionError("service is down")

    decision = PolicyServiceAdapter(UnavailableService()).evaluate(make_request())

    assert decision.allowed is False
    assert decision.reason == "Policy service unavailable."


def test_adapter_fails_closed_on_malformed_response():
    class MalformedService:
        def decide(self, request):
            return {"allowed": True, "reason": "allowed"}

    decision = PolicyServiceAdapter(MalformedService()).evaluate(make_request())

    assert decision.allowed is False
    assert "malformed" in decision.reason


def test_adapter_fails_closed_on_tenant_mismatch():
    class WrongTenantService:
        def decide(self, request):
            return PolicyDecisionResponse(
                True,
                "allowed",
                provenance(tenant_id="org-other"),
            )

    decision = PolicyServiceAdapter(WrongTenantService()).evaluate(make_request())

    assert decision.allowed is False
    assert "tenant mismatch" in decision.reason
