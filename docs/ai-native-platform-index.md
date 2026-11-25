# AI-Native Data Platform — Architecture Set

**Status:** Proposed
**Decision gate:** Architecture agreement required before implementation
**Last reviewed:** 2026-11-25
**Baseline:** `c1345bab06b7c89062b6484e262dc5df1557dd79`

This document set describes a greenfield AI-native data platform derived from
the proven security and governance capabilities in this repository. It is
intentionally design-only: no implementation should begin until the target
architecture and its invariants are agreed.

## Documents

1. [Existing architecture assessment](ai-native-platform-assessment.md)
2. [Target AI-native architecture](ai-native-platform-architecture.md)
3. [Capability mapping](ai-native-capability-map.md)
4. [Proposed repository structure](ai-native-repository-structure.md)
5. [Phased implementation roadmap](ai-native-roadmap.md)
6. [Semantic catalog foundation](phase3-semantic-catalog.md)

## Decision required

Approve or revise:

- the platform boundary and autonomy levels;
- the delegated agent identity model;
- the capability and approval model;
- the policy decision contract;
- memory scope, retention, and classification rules;
- the invariant that all data access remains inside the deterministic execution
  kernel.

## Non-negotiable design invariant

Agents may reason, plan, retrieve context, and propose actions, but they may
execute only typed, policy-authorized capabilities. No agent receives raw
database credentials or bypasses tenant resolution, policy evaluation, SQL
validation, masking, resource controls, or audit.
