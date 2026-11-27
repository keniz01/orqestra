"""Production application factory for the governed read control service."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from control_api import (
    AsgiGovernedReadApplication,
    Auth0Configuration,
    Auth0PrincipalResolver,
    GovernedReadControl,
)
from execution_kernel import (
    ExecutionKernel,
    Principal,
    QueryPlan,
    RulePolicyEvaluator,
    TenantBinding,
    TenantBindingRegistry,
)
from governed_orchestrator import (
    GovernedReadOrchestrator,
    GovernedReadWorkflowService,
    InMemoryWorkflowReportStore,
)
from memory_service import InMemoryMemoryStore
from read_workflows import (
    ContextAssembler,
    ContextPolicy,
    DeterministicReadWorkflowPlanner,
    KernelCapabilityExecutor,
    KernelReadRequest,
)
from semantic_catalog import InMemorySemanticCatalog
from task_runtime import InMemoryTaskStore
from workflow_reliability import (
    InMemoryCancellationStore,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
)
from governance import InMemoryGovernanceLedger


class _PostgresQueryExecutor:
    """Synchronous read-only PostgreSQL executor used behind ASGI worker threads."""

    def execute(self, binding, query, params):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL execution.") from exc

        with psycopg.connect(
            binding.target,
            connect_timeout=float(os.getenv("ORQESTRA_DB_CONNECT_TIMEOUT", "5")),
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                timeout_ms = int(float(os.getenv("ORQESTRA_DB_TIMEOUT", "30")) * 1000)
                cursor.execute(f"SET LOCAL statement_timeout = '{timeout_ms}ms'")
                cursor.execute(query.sql, params)
                return tuple(cursor.fetchmany(5001))


class _ServerOwnedQueryBuilder:
    def __init__(self, database_id: str) -> None:
        self._database_id = database_id

    def build(self, principal: Principal, step) -> KernelReadRequest:
        del principal
        return KernelReadRequest(
            database_id=self._database_id,
            plan=QueryPlan("SELECT 1 AS governed_read"),
        )


class _CatalogContextProvider:
    def __init__(self, catalog_path: str) -> None:
        self._assembler = ContextAssembler(
            InMemorySemanticCatalog(),
            InMemoryMemoryStore(),
        )
        self._catalog_path = catalog_path

    def build(self, principal: Principal, goal: str):
        del goal, self._catalog_path
        return self._assembler.assemble(principal, ContextPolicy())


def create_application() -> AsgiGovernedReadApplication:
    """Build the service from server-owned environment and secret-file settings."""

    auth = Auth0PrincipalResolver(Auth0Configuration.from_environment())
    tenant_bindings = _tenant_bindings()
    database_id = _required_setting("ORQESTRA_DATABASE_ID", default="analytics")
    policy = RulePolicyEvaluator(
        allow_rules=(
            {
                "capability": "data.execute_read_query",
                "roles": tuple(
                    role.strip()
                    for role in _required_setting(
                        "ORQESTRA_ALLOWED_ROLES", default="viewer"
                    ).split(",")
                    if role.strip()
                ),
                "database_id": database_id,
            },
        )
    )
    kernel = ExecutionKernel(
        tenants=TenantBindingRegistry(tenant_bindings),
        policy=policy,
        executor=_PostgresQueryExecutor(),
        audit_sink=lambda event: None,
    )
    capability_executor = KernelCapabilityExecutor(
        kernel,
        {
            "catalog.search_semantic_metadata": _ServerOwnedQueryBuilder(database_id),
            "data.plan_read_query": _ServerOwnedQueryBuilder(database_id),
        },
    )
    report_store = InMemoryWorkflowReportStore()
    orchestrator = GovernedReadOrchestrator(
        tasks=InMemoryTaskStore(),
        leases=InMemoryLeaseStore(),
        checkpoints=InMemoryCheckpointStore(),
        cancellations=InMemoryCancellationStore(),
        ledger=InMemoryGovernanceLedger(),
        executor=capability_executor,
        report_store=report_store,
    )
    service = GovernedReadWorkflowService(
        orchestrator,
        DeterministicReadWorkflowPlanner(),
    )
    control = GovernedReadControl(
        service,
        _CatalogContextProvider(_required_setting("ORQESTRA_CATALOG_DB", default=":memory:")),
    )
    return AsgiGovernedReadApplication(
        control,
        auth,
        readiness_check=lambda: bool(tenant_bindings),
    )


def _tenant_bindings() -> dict[tuple[str, str], TenantBinding]:
    raw = _read_setting("ORQESTRA_TENANT_DATABASES")
    if not raw:
        raise ValueError("ORQESTRA_TENANT_DATABASES or ORQESTRA_TENANT_DATABASES_FILE is required.")
    data = json.loads(raw)
    if not isinstance(data, Mapping):
        raise ValueError("Tenant database configuration must be a JSON object.")
    bindings: dict[tuple[str, str], TenantBinding] = {}
    for org_id, databases in data.items():
        if not isinstance(databases, Mapping):
            raise ValueError("Each tenant database entry must be a JSON object.")
        for database_id, target in databases.items():
            bindings[(str(org_id), str(database_id))] = TenantBinding(
                str(org_id),
                str(database_id),
                f"{org_id}:{database_id}",
                str(target),
            )
    if not bindings:
        raise ValueError("Tenant database configuration must not be empty.")
    return bindings


def _required_setting(name: str, *, default: str | None = None) -> str:
    value = _read_setting(name)
    if value:
        return value
    if default is not None:
        return default
    raise ValueError(f"{name} is required.")


def _read_setting(name: str) -> str:
    value = os.getenv(name)
    if value is not None and value.strip():
        return value.strip()
    file_name = os.getenv(f"{name}_FILE")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return ""


app = create_application()
