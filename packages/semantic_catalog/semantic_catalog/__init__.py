"""Tenant-scoped semantic catalog contracts and reference implementation."""

from .catalog import CatalogConflict, CatalogPolicy, CatalogScopeError, InMemorySemanticCatalog
from .models import (
    Classification,
    Column,
    ColumnMetadata,
    DataSource,
    DataSourceMetadata,
    Freshness,
    Provenance,
    SourceKind,
    Table,
    TableMetadata,
)
from .repository import (
    CatalogRepository,
    MetadataCollector,
    MetadataIngestionService,
    SQLiteSemanticCatalog,
)
from .semantic_models import (
    BusinessMetric,
    LineageEdge,
    SemanticEntity,
    SemanticRelationship,
)
from .semantic_repository import SemanticFactRepository, SQLiteSemanticFacts

__all__ = [
    "CatalogConflict",
    "CatalogPolicy",
    "CatalogScopeError",
    "CatalogRepository",
    "BusinessMetric",
    "Classification",
    "Column",
    "ColumnMetadata",
    "DataSource",
    "DataSourceMetadata",
    "Freshness",
    "InMemorySemanticCatalog",
    "MetadataCollector",
    "MetadataIngestionService",
    "Provenance",
    "SourceKind",
    "SemanticEntity",
    "SemanticFactRepository",
    "SemanticRelationship",
    "SQLiteSemanticFacts",
    "SQLiteSemanticCatalog",
    "LineageEdge",
    "Table",
    "TableMetadata",
]
