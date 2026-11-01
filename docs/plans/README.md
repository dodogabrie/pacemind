# Plans Index

Design and implementation plans for PaceMind. Each plan is a living document:
update **Status** as work lands, and link the PR that implements it.

## Active epics

| Plan | Status | Summary |
|---|---|---|
| [Multi-source activities](multi-source-activities/README.md) | 📋 planned | Decouple the product from Strava: independent identity, source-agnostic activity storage, multi-format file ingest, direct device integrations. |

## Single-issue plans

| Plan | Status | Summary |
|---|---|---|
| [Plan generation rate limit bug](plan-generation-rate-limit-bug.md) | 🔴 open | Plan creation hits Anthropic 429 because the agent takes the per-week LLM path instead of the deterministic engine. |
| [Workout system review](workout-system-review.md) | ✅ complete | Coach language, LiteLLM proxy, plan engine consistency. (Written in Italian.) |

## Conventions

- One directory per epic, with a `README.md` index and numbered detail files.
- Detail files are self-contained: a reader should be able to start from any one
  of them without holding the others in memory.
- Reference code as `path/to/file.py:123` so links stay clickable.
- Plans are written in **English**, regardless of the language of the
  conversation that produced them.
- When a plan uncovers a bug that is not fixed in the same session, follow the
  TODO + GitHub issue rule in `CLAUDE.md`.
