"""Server-owned capability adapters for governed read workflow steps."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from execution_kernel import ExecutionKernel, Principal, QueryPlan

from .contracts import (
    CapabilityResultState,
    Evidence,
    GovernedCapabilityResult,
    ReadPlanStep,
)


@dataclass(frozen=True, slots=True)
class KernelReadRequest:
    """Server-owned query materialization for one typed workflow step."""

    database_id: str
    plan: QueryPlan


class ReadQueryBuilder(Protocol):
    """Builds SQL only inside the trusted capability adapter boundary."""

    def build(self, principal: Principal, step: ReadPlanStep) -> KernelReadRequest:
        """Return a server-owned database binding and read-only query plan."""


class KernelCapabilityExecutor:
    """Execute typed steps through the execution kernel, never from raw inputs."""

    def __init__(
        self,
        kernel: ExecutionKernel,
        builders: dict[str, ReadQueryBuilder],
    ) -> None:
        self._kernel = kernel
        self._builders = dict(builders)

    def execute(
        self,
        principal: Principal,
        task_id: str,
        step: ReadPlanStep,
    ) -> GovernedCapabilityResult:
        builder = self._builders.get(step.capability)
        if builder is None:
            raise PermissionError(f"No governed adapter for {step.capability}.")
        request = builder.build(principal, step)
        query_hash = hashlib.sha256(
            request.plan.sql.strip().encode("utf-8")
        ).hexdigest()
        result = self._kernel.execute(
            principal=principal,
            database_id=request.database_id,
            plan=request.plan,
            task_id=task_id,
        )
        return GovernedCapabilityResult(
            step_id=step.step_id,
            capability=step.capability,
            state=CapabilityResultState.SUCCEEDED,
            value=result.rows,
            evidence=(
                Evidence(
                    source="execution-kernel",
                    reference=f"query:{query_hash}",
                    capability=step.capability,
                    metadata={
                        "database_id": request.database_id,
                        "truncated": result.truncated,
                        "result_bytes": result.result_bytes,
                    },
                    query_hash=query_hash,
                ),
            ),
            confidence=0.75 if result.truncated else 1.0,
            query_hash=query_hash,
        )
