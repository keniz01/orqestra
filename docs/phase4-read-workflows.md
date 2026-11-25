# Phase 4 read workflow contracts

Read workflows are bounded, model-independent intent contracts. A planner
produces a goal and typed capability steps; it does not receive credentials or
executable SQL. A runner consumes only results injected by an already-governed
capability adapter. The in-memory runner is a reference implementation and
does not execute, authorize, or discover capabilities.

Each successful result includes provenance evidence and a confidence score in
the range `0..1`. Missing evidence or confidence prevents completion. Direct
SQL and credential-shaped inputs are rejected at the plan boundary.
