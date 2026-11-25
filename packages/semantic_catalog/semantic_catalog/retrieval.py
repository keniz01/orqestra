"""Tenant-filtered embedding and retrieval contracts."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol

from execution_kernel import Principal

from .catalog import CatalogPolicy
from .models import Classification


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> tuple[float, ...]:
        ...


class HashEmbeddingProvider:
    """Deterministic local embedding suitable for a dependency-free index."""

    def __init__(self, dimensions: int = 32) -> None:
        if dimensions < 4:
            raise ValueError("dimensions must be at least 4")
        self._dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        tokens = text.lower().split()
        vector = [0.0] * self._dimensions
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return tuple(value / magnitude for value in vector) if magnitude else tuple(vector)


class SQLiteEmbeddingIndex:
    """Durable, tenant-scoped vector index with policy filtering before ranking."""

    def __init__(
        self,
        database: str | sqlite3.Connection,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self._connection = (
            database
            if isinstance(database, sqlite3.Connection)
            else sqlite3.connect(database)
        )
        self._connection.row_factory = sqlite3.Row
        self._provider = provider or HashEmbeddingProvider()
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_embeddings (
                tenant_id TEXT NOT NULL,
                fact_id TEXT NOT NULL,
                text TEXT NOT NULL,
                classification INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, fact_id)
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def index(
        self,
        principal: Principal,
        fact_id: str,
        text: str,
        classification: Classification = Classification.INTERNAL,
    ) -> None:
        if not fact_id.strip() or not text.strip():
            raise ValueError("fact_id and text must not be empty")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO catalog_embeddings
                    (tenant_id, fact_id, text, classification, vector_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, fact_id) DO UPDATE SET
                    text = excluded.text,
                    classification = excluded.classification,
                    vector_json = excluded.vector_json
                """,
                (
                    principal.org_id,
                    fact_id.strip(),
                    text.strip(),
                    int(classification),
                    json.dumps(self._provider.embed(text)),
                ),
            )

    def search(
        self,
        principal: Principal,
        query: str,
        *,
        policy: CatalogPolicy | None = None,
        limit: int = 10,
    ) -> tuple[tuple[str, float, str], ...]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")
        active_policy = policy or CatalogPolicy()
        query_vector = self._provider.embed(query)
        rows = self._connection.execute(
            """
            SELECT fact_id, text, classification, vector_json
            FROM catalog_embeddings
            WHERE tenant_id = ? AND classification <= ?
            """,
            (principal.org_id, int(active_policy.max_classification)),
        ).fetchall()
        ranked = sorted(
            (
                (
                    row["fact_id"],
                    _cosine(query_vector, tuple(json.loads(row["vector_json"]))),
                    row["text"],
                )
                for row in rows
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return tuple(ranked[:limit])


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions must match")
    return sum(a * b for a, b in zip(left, right, strict=True))
