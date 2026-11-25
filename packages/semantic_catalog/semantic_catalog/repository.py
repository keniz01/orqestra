"""Durable tenant-scoped semantic catalog persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Protocol

from execution_kernel import Principal
from governance import GovernanceEvent, GovernanceLedger

from .catalog import CatalogPolicy, CatalogScopeError
from .models import (
    Classification,
    ColumnMetadata,
    DataSourceMetadata,
    Freshness,
    Provenance,
    SourceKind,
    TableMetadata,
)


class CatalogRepository(Protocol):
    """Persistence contract for catalog sources."""

    def upsert(self, source: DataSourceMetadata) -> None:
        ...

    def read(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[DataSourceMetadata, ...]:
        ...

    def get_source(
        self,
        principal: Principal,
        source_id: str,
        policy: CatalogPolicy | None = None,
    ) -> DataSourceMetadata:
        ...


class MetadataCollector(Protocol):
    """Connector-neutral source metadata collector."""

    def collect(self, principal: Principal) -> Iterable[DataSourceMetadata]:
        ...


class MetadataIngestionService:
    """Persist metadata collected for the trusted tenant principal."""

    def __init__(
        self,
        repository: CatalogRepository,
        ledger: GovernanceLedger | None = None,
    ) -> None:
        self._repository = repository
        self._ledger = ledger

    def ingest(
        self,
        principal: Principal,
        collector: MetadataCollector,
    ) -> tuple[DataSourceMetadata, ...]:
        sources = tuple(collector.collect(principal))
        if any(source.tenant_id != principal.org_id for source in sources):
            raise CatalogScopeError("collector returned metadata for another tenant")
        for source in sources:
            _require_provenance(source)
            self._repository.upsert(source)
            if self._ledger is not None:
                self._ledger.append(
                    GovernanceEvent(
                        event_id=f"catalog.ingested:{source.tenant_id}:{source.source_id}",
                        org_id=source.tenant_id,
                        event_type="catalog.ingested",
                        actor_user_id=principal.user_id,
                        decision="allow",
                        reason="Catalog metadata ingested.",
                        capability="semantic_catalog.ingest",
                        payload={
                            "source_id": source.source_id,
                            "source_kind": source.kind.value,
                            "source_system": source.provenance.source_system,
                            "source_object": source.provenance.source_object,
                            "collector": source.provenance.collector,
                        },
                    )
                )
        return sources


def _require_provenance(source: DataSourceMetadata) -> None:
    if source.provenance is None:
        raise ValueError("source provenance is required for ingestion")
    for table in source.tables:
        if table.provenance is None:
            raise ValueError("table provenance is required for ingestion")
        for column in table.columns:
            if column.provenance is None:
                raise ValueError("column provenance is required for ingestion")


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _freshness_json(value: Freshness | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"last_refreshed_at": _timestamp(value.last_refreshed_at), "max_age_seconds": value.max_age.total_seconds()}


def _freshness(value: str | None) -> Freshness | None:
    if value is None:
        return None
    data = json.loads(value)
    return Freshness(_datetime(str(data["last_refreshed_at"])), timedelta(seconds=float(data["max_age_seconds"])))


def _provenance_json(value: Provenance | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "source_system": value.source_system,
        "source_object": value.source_object,
        "collected_at": _timestamp(value.collected_at),
        "collector": value.collector,
    }


def _provenance(value: str | None) -> Provenance | None:
    if value is None:
        return None
    data = json.loads(value)
    return Provenance(
        str(data["source_system"]),
        str(data["source_object"]),
        _datetime(str(data["collected_at"])),
        str(data["collector"]),
    )


def _serialize_source(source: DataSourceMetadata) -> str:
    return json.dumps(
        {
            "tenant_id": source.tenant_id,
            "source_id": source.source_id,
            "name": source.name,
            "kind": source.kind.value,
            "classification": int(source.classification),
            "description": source.description,
            "provenance": _provenance_json(source.provenance),
            "freshness": _freshness_json(source.freshness),
            "tables": [
                {
                    "tenant_id": table.tenant_id,
                    "source_id": table.source_id,
                    "table_id": table.table_id,
                    "name": table.name,
                    "classification": int(table.classification),
                    "description": table.description,
                    "provenance": _provenance_json(table.provenance),
                    "freshness": _freshness_json(table.freshness),
                    "columns": [
                        {
                            "tenant_id": column.tenant_id,
                            "source_id": column.source_id,
                            "table_id": column.table_id,
                            "name": column.name,
                            "data_type": column.data_type,
                            "classification": int(column.classification),
                            "nullable": column.nullable,
                            "description": column.description,
                            "provenance": _provenance_json(column.provenance),
                            "freshness": _freshness_json(column.freshness),
                        }
                        for column in table.columns
                    ],
                }
                for table in source.tables
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _deserialize_source(value: str) -> DataSourceMetadata:
    data = json.loads(value)
    tables = tuple(
        TableMetadata(
            tenant_id=str(table["tenant_id"]),
            source_id=str(table["source_id"]),
            table_id=str(table["table_id"]),
            name=str(table["name"]),
            classification=Classification(int(table["classification"])),
            description=str(table["description"]),
            provenance=_provenance(json.dumps(table["provenance"]) if table["provenance"] is not None else None),
            freshness=_freshness(json.dumps(table["freshness"]) if table["freshness"] is not None else None),
            columns=tuple(
                ColumnMetadata(
                    tenant_id=str(column["tenant_id"]),
                    source_id=str(column["source_id"]),
                    table_id=str(column["table_id"]),
                    name=str(column["name"]),
                    data_type=str(column["data_type"]),
                    classification=Classification(int(column["classification"])),
                    nullable=bool(column["nullable"]),
                    description=str(column["description"]),
                    provenance=_provenance(json.dumps(column["provenance"]) if column["provenance"] is not None else None),
                    freshness=_freshness(json.dumps(column["freshness"]) if column["freshness"] is not None else None),
                )
                for column in table["columns"]
            ),
        )
        for table in data["tables"]
    )
    return DataSourceMetadata(
        tenant_id=str(data["tenant_id"]),
        source_id=str(data["source_id"]),
        name=str(data["name"]),
        kind=SourceKind(str(data["kind"])),
        classification=Classification(int(data["classification"])),
        description=str(data["description"]),
        provenance=_provenance(json.dumps(data["provenance"]) if data["provenance"] is not None else None),
        freshness=_freshness(json.dumps(data["freshness"]) if data["freshness"] is not None else None),
        tables=tables,
    )


class SQLiteSemanticCatalog:
    """SQLite-backed implementation of the semantic catalog contract."""

    def __init__(self, database: str | sqlite3.Connection) -> None:
        self._connection = (
            database
            if isinstance(database, sqlite3.Connection)
            else sqlite3.connect(database)
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_sources (
                tenant_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, source_id)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def upsert(self, source: DataSourceMetadata) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO catalog_sources (tenant_id, source_id, metadata_json)
                VALUES (?, ?, ?)
                ON CONFLICT (tenant_id, source_id) DO UPDATE SET
                    metadata_json = excluded.metadata_json
                """,
                (source.tenant_id, source.source_id, _serialize_source(source)),
            )

    def read(
        self,
        principal: Principal,
        policy: CatalogPolicy | None = None,
    ) -> tuple[DataSourceMetadata, ...]:
        active_policy = policy or CatalogPolicy()
        rows = self._connection.execute(
            """
            SELECT metadata_json FROM catalog_sources
            WHERE tenant_id = ?
            ORDER BY source_id
            """,
            (principal.org_id,),
        ).fetchall()
        return tuple(
            self._filter_source(_deserialize_source(row["metadata_json"]), active_policy)
            for row in rows
            if active_policy.allows_source(_deserialize_source(row["metadata_json"]))
        )

    def get_source(
        self,
        principal: Principal,
        source_id: str,
        policy: CatalogPolicy | None = None,
    ) -> DataSourceMetadata:
        row = self._connection.execute(
            """
            SELECT metadata_json FROM catalog_sources
            WHERE tenant_id = ? AND source_id = ?
            """,
            (principal.org_id, source_id),
        ).fetchone()
        if row is None:
            exists = self._connection.execute(
                "SELECT 1 FROM catalog_sources WHERE source_id = ? LIMIT 1",
                (source_id,),
            ).fetchone()
            if exists is not None:
                raise CatalogScopeError("source is not available to this tenant")
            raise KeyError(source_id)
        source = _deserialize_source(row["metadata_json"])
        active_policy = policy or CatalogPolicy()
        if not active_policy.allows_source(source):
            raise CatalogScopeError("source is not available under this policy")
        return self._filter_source(source, active_policy)

    @staticmethod
    def _filter_source(
        source: DataSourceMetadata,
        policy: CatalogPolicy,
    ) -> DataSourceMetadata:
        tables = tuple(
            TableMetadata(
                tenant_id=table.tenant_id,
                source_id=table.source_id,
                table_id=table.table_id,
                name=table.name,
                classification=table.classification,
                description=table.description,
                provenance=table.provenance,
                freshness=table.freshness,
                columns=tuple(
                    column for column in table.columns if policy.allows_column(column)
                ),
            )
            for table in source.tables
            if policy.allows_table(table)
        )
        return DataSourceMetadata(
            tenant_id=source.tenant_id,
            source_id=source.source_id,
            name=source.name,
            kind=source.kind,
            classification=source.classification,
            description=source.description,
            provenance=source.provenance,
            freshness=source.freshness,
            tables=tables,
        )
