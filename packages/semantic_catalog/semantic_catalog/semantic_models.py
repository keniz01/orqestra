"""Semantic data-plane contracts for catalog facts."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Classification, Freshness, Provenance, _required_text


@dataclass(frozen=True, slots=True)
class SemanticEntity:
    tenant_id: str
    entity_id: str
    name: str
    description: str = ""
    classification: Classification = Classification.INTERNAL
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "entity_id", "name"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")


@dataclass(frozen=True, slots=True)
class SemanticRelationship:
    tenant_id: str
    relationship_id: str
    from_entity_id: str
    to_entity_id: str
    relationship_type: str
    classification: Classification = Classification.INTERNAL
    description: str = ""
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "relationship_id",
            "from_entity_id",
            "to_entity_id",
            "relationship_type",
        ):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")


@dataclass(frozen=True, slots=True)
class BusinessMetric:
    tenant_id: str
    metric_id: str
    name: str
    definition: str
    classification: Classification = Classification.INTERNAL
    description: str = ""
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "metric_id", "name", "definition"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")


@dataclass(frozen=True, slots=True)
class LineageEdge:
    tenant_id: str
    lineage_id: str
    upstream: str
    downstream: str
    transformation: str = ""
    classification: Classification = Classification.INTERNAL
    provenance: Provenance | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "lineage_id", "upstream", "downstream"):
            object.__setattr__(
                self, field_name, _required_text(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "transformation", self.transformation.strip())
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")
