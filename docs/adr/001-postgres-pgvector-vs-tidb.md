# ADR-001: Postgres + pgvector as the single substrate (vs TiDB)

## Status

Accepted — 2026-05-16

## Context

The `sentinel-memory` project implements the memory layer of an agentic security
analyst: alerts (transactional facts), vector embeddings (RAG + semantic memory),
episodic memory, long-term memory (LTM) and an immutable audit log.

The reference book (chapters 3 and 4) pushes hard for **TiDB** as the unified
substrate for SQL + vectors + auditing, arguing that a distributed engine is
the only one capable of supporting the "semantic-transactional join" pattern
without operational friction.

Before adopting that recommendation we have to ask:

- Is the architectural thesis ("one substrate, ACID, native vectors") specific
  to TiDB, or is it satisfied by other engines?
- Does the scope of this project (portfolio, local-first, fewer than 1M
  vectors) justify a distributed engine?
- What cost in *vendor lock-in* and cloud operations are we willing to pay?

## Decision

Adopt **Postgres 16 + the pgvector 0.7+ extension** as the single engine for
every table in the system (alerts, playbooks, episodic memory, LTM, audit).

No second engine. No external vector DB. No managed cloud service.

## Rationale

1. **Fulfils the book's thesis without locking us to a vendor.** Postgres +
   pgvector unifies relational SQL and vector search in a single engine with
   strict ACID. The important architectural claim — "avoid two engines you
   have to keep in sync" — holds for any engine that combines both models,
   not just TiDB.
2. **Strict ACID, same as TiDB.** Postgres offers real serializable
   transactions. At the target size there is no functional difference.
3. **Operational maturity.** Postgres has decades of tooling: `pg_dump`,
   `pgbench`, physical and logical replication, extensions, mature
   observability. TiDB has less than a decade of broad production use.
4. **Local-first.** The full stack runs with `docker compose up` and no
   cloud account. For a portfolio project this is decisive: any reviewer
   can clone and run without signing up for a trial.
5. **Drop-in upgrade path.** If real horizontal scale is ever needed,
   **Citus**, **CockroachDB** or **TiDB** itself are low-effort migrations
   because they preserve the Postgres wire protocol. Today's choice does
   not close tomorrow's doors.
6. **Industry standard.** Postgres is an obvious read for any senior
   engineer. TiDB requires extra onboarding.

## Consequences

### Positive

- Zero vendor lock-in.
- Zero cloud cost throughout the portfolio phase.
- A recognisable stack: any reviewer understands `psql` and `pgvector`.
- Reproducible setup: `docker compose up` and you are done.
- Immutable audit implementable with native triggers (no proprietary
  features required).

### Negative

- **No native horizontal scale.** More than one write node requires
  migrating to Citus / Cockroach / TiDB. Acceptable: the scope is
  fewer than 1M vectors on a single node.
- **HNSW in pgvector consumes memory.** Mitigable with `ivfflat` if
  the corpus grows, at the cost of recall.
- **No out-of-the-box geo-distributed replicas.** Out of scope for
  the portfolio.

## Alternatives evaluated

| Alternative | Why it was dropped |
| --- | --- |
| **TiDB Cloud** | Commercial bias from the book; forces a cloud account; adds friction for reviewers; horizontal-scale advantages do not apply at this scope. |
| **CockroachDB** | Overkill for a single-node local setup; same cluster friction without concrete benefits for fewer than 1M rows. |
| **Postgres + Pinecone** | Breaks the *single-substrate* thesis: two engines to keep consistent, two APIs, extra synchronisation. Increases failure surface and cloud cost. |
| **Postgres + Qdrant/Weaviate** | Same problem: two engines, two query languages. Loses the "semantic-transactional join" that is the central pattern of Ch. 3. |
| **DuckDB + vector extension** | Excellent for analytics; not suitable as an OLTP system with concurrency or transactional immutable auditing. |

## Implementation notes

- Embedding model: `sentence-transformers/all-MiniLM-L6-v2` → `vector(384)`.
- Index: `hnsw` with `vector_cosine_ops` (high recall, moderate memory).
- Audit-log immutability: `BEFORE UPDATE` and `BEFORE DELETE` triggers that
  raise an exception. Governance lives in the database, not in the
  application.
- Temporal versioning: `valid_from` / `valid_to` columns on `alerts`
  enable "AS OF" queries without an extra extension.

## Review

Reopen this ADR if:

- The corpus grows beyond 5M vectors and HNSW recall degrades.
- A multi-region active-active requirement appears.
- The project stops being a portfolio and moves into production with hard SLAs.
