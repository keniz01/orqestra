"""Tenant-scoped persistence for semantic catalog facts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Protocol

from execution_kernel import Principal

from .catalog import CatalogPolicy
from .models import Classification, Freshness, Provenance
from .semantic_models import (
    BusinessMetric,
    LineageEdge,
    SemanticEntity,
    SemanticRelationship,
)


class SemanticFactRepository(Protocol):
    def put_entity(self, value: SemanticEntity) -> None:
        ...

    def put_relationship(self, value: SemanticRelationship) -> None:
        ...

    def put_metric(self, value: BusinessMetric) -> None:
        ...

    def put_lineage(self, value: LineageEdge) -> None:
        ...

    def read_entities(
        self, principal: Principal, policy: CatalogPolicy | None = None
    ) -> tuple[SemanticEntity, ...]:
        ...


def _fact_json(value: object) -> str:
    if isinstance(value, SemanticEntity):
        data = {
            "tenant_id": value.tenant_id,
            "entity_id": value.entity_id,
            "name": value.name,
            "description": value.description,
        }
    elif isinstance(value, SemanticRelationship):
        data = {
            "tenant_id": value.tenant_id,
            "relationship_id": value.relationship_id,
            "from_entity_id": value.from_entity_id,
            "to_entity_id": value.to_entity_id,
            "relationship_type": value.relationship_type,
            "description": value.description,
        }
    elif isinstance(value, BusinessMetric):
        data = {
            "tenant_id": value.tenant_id,
            "metric_id": value.metric_id,
            "name": value.name,
            "definition": value.definition,
            "description": value.description,
        }
    elif isinstance(value, LineageEdge):
        data = {
            "tenant_id": value.tenant_id,
            "lineage_id": value.lineage_id,
            "upstream": value.upstream,
            "downstream": value.downstream,
            "transformation": value.transformation,
        }
    else:
        raise TypeError("unsupported semantic fact")
    data.update(
        {
            "classification": int(value.classification),
            "provenance": _provenance_json(value.provenance),
            "freshness": _freshness_json(value.freshness),
        }
    )
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _provenance_json(value: Provenance | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "source_system": value.source_system,
        "source_object": value.source_object,
        "collected_at": value.collected_at.isoformat(),
        "collector": value.collector,
    }


def _freshness_json(value: Freshness | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "last_refreshed_at": value.last_refreshed_at.isoformat(),
        "max_age_seconds": value.max_age.total_seconds(),
    }


class SQLiteSemanticFacts:
    """SQLite-backed entities, relationships, metrics, and lineage."""

    def __init__(self, database: str | sqlite3.Connection) -> None:
        self._connection = (
            database
            if isinstance(database, sqlite3.Connection)
            else sqlite3.connect(database)
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_facts (
                tenant_id TEXT NOT NULL,
                fact_type TEXT NOT NULL,
                fact_id TEXT NOT NULL,
                classification INTEGER NOT NULL,
                fact_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, fact_type, fact_id)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def _put(self, fact_type: str, fact_id: str, value: object) -> None:
        tenant_id = getattr(value, "tenant_id")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO semantic_facts
                    (tenant_id, fact_type, fact_id, classification, fact_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, fact_type, fact_id) DO UPDATE SET
                    classification = excluded.classification,
                    fact_json = excluded.fact_json
                """,
                (
                    tenant_id,
                    fact_type,
                    fact_id,
                    int(getattr(value, "classification")),
                    _fact_json(value),
                ),
            )

    def put_entity(self, value: SemanticEntity) -> None:
        self._put("entity", value.entity_id, value)

    def put_relationship(self, value: SemanticRelationship) -> None:
        self._put("relationship", value.relationship_id, value)

    def put_metric(self, value: BusinessMetric) -> None:
        self._put("metric", value.metric_id, value)

    def put_lineage(self, value: LineageEdge) -> None:
        self._put("lineage", value.lineage_id, value)

    def read_entities(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[SemanticEntity, ...]:
        active_policy = policy or CatalogPolicy()
        rows = self._connection.execute(
            """
            SELECT fact_json FROM semantic_facts
            WHERE tenant_id = ? AND fact_type = ?
            ORDER BY fact_id
            """,
            (principal.org_id, "entity"),
        ).fetchall()
        values = tuple(_entity_from_json(row["fact_json"]) for row in rows)
        return tuple(
            value
            for value in values
            if value.tenant_id == principal.org_id
            and value.classification <= active_policy.max_classification
        )

    def read_relationships(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[SemanticRelationship, ...]:
        return self._read_type(principal, "relationship", _relationship_from_json, policy)

    def read_metrics(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[BusinessMetric, ...]:
        return self._read_type(principal, "metric", _metric_from_json, policy)

    def read_lineage(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[LineageEdge, ...]:
        return self._read_type(principal, "lineage", _lineage_from_json, policy)

    def _read_type(self, principal: Principal, fact_type: str, parser, policy):
        active_policy = policy or CatalogPolicy()
        rows = self._connection.execute(
            """
            SELECT fact_json FROM semantic_facts
            WHERE tenant_id = ? AND fact_type = ?
            ORDER BY fact_id
            """,
            (principal.org_id, fact_type),
        ).fetchall()
        return tuple(
            value
            for value in (parser(row["fact_json"]) for row in rows)
            if value.classification <= active_policy.max_classification
        )


def _common(data: dict[str, object]) -> dict[str, object]:
    provenance = data.get("provenance")
    freshness = data.get("freshness")
    return {
        "tenant_id": str(data["tenant_id"]),
        "classification": Classification(int(data["classification"])),
        "provenance": (
            Provenance(
                str(provenance["source_system"]),
                str(provenance["source_object"]),
                datetime.fromisoformat(str(provenance["collected_at"])),
                str(provenance["collector"]),
            )
            if provenance is not None
            else None
        ),
        "freshness": (
            Freshness(
                datetime.fromisoformat(str(freshness["last_refreshed_at"])),
                timedelta(seconds=float(freshness["max_age_seconds"])),
            )
            if freshness is not None
            else None
        ),
    }


def _entity_from_json(value: str) -> SemanticEntity:
    data = json.loads(value)
    return SemanticEntity(entity_id=str(data["entity_id"]), name=str(data["name"]), description=str(data["description"]), **_common(data))


def _relationship_from_json(value: str) -> SemanticRelationship:
    data = json.loads(value)
    return SemanticRelationship(
        relationship_id=str(data["relationship_id"]),
        from_entity_id=str(data["from_entity_id"]),
        to_entity_id=str(data["to_entity_id"]),
        relationship_type=str(data["relationship_type"]),
        description=str(data["description"]),
        **_common(data),
    )


def _metric_from_json(value: str) -> BusinessMetric:
    data = json.loads(value)
    return BusinessMetric(
        metric_id=str(data["metric_id"]),
        name=str(data["name"]),
        definition=str(data["definition"]),
        description=str(data["description"]),
        **_common(data),
    )


def _lineage_from_json(value: str) -> LineageEdge:
    data = json.loads(value)
    return LineageEdge(
        lineage_id=str(data["lineage_id"]),
        upstream=str(data["upstream"]),
        downstream=str(data["downstream"]),
        transformation=str(data["transformation"]),
        **_common(data),
    )
