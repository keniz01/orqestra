# AI-Native Data Platform — Architecture Set

**Status:** Approved for implementation
**Decision gate:** Phase 5 product implementation
**Last reviewed:** 2026-11-27
**Baseline:** `c1345bab06b7c89062b6484e262dc5df1557dd79`

This document set describes an AI-native data platform derived from the proven
security and governance capabilities in this repository. The initial
architecture and invariants are approved; implementation proceeds through the
phased roadmap.

## Documents

1. [Existing architecture assessment](ai-native-platform-assessment.md)
2. [Target AI-native architecture](ai-native-platform-architecture.md)
3. [Capability mapping](ai-native-capability-map.md)
4. [Proposed repository structure](ai-native-repository-structure.md)
5. [Phased implementation roadmap](ai-native-roadmap.md)
6. [Semantic catalog foundation](phase3-semantic-catalog.md)
7. [Approved architecture decision record](architecture-decision-record.md)

## Approved decisions

The approved identity, connector, model, approval, classification, retention,
audit, and autonomy decisions are recorded in
[`architecture-decision-record.md`](architecture-decision-record.md).

## Non-negotiable design invariant

Agents may reason, plan, retrieve context, and propose actions, but they may
execute only typed, policy-authorized capabilities. No agent receives raw
database credentials or bypasses tenant resolution, policy evaluation, SQL
validation, masking, resource controls, or audit.
