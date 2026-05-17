# ADR-001: Postgres + pgvector as the single substrate (vs TiDB)

## Status

Accepted — 2026-05-16

## Context

The `sentinel-memory` project implements the memory layer of an agentic security
analyst: alerts (transactional facts), vector embeddings (RAG + semantic memory),
episodic memory, long-term memory (LTM) and an immutable audit log.

The reference book (chapters 3 and 4) makes a compelling case for **TiDB**
as the unified substrate for SQL + vectors + auditing, arguing that a
single ACID engine for facts and vectors is what makes patterns like the
"semantic-transactional join" feasible without operational friction.

The architectural thesis is sound. The remaining question is which engine
best serves *this* project:

- Is the thesis ("one substrate, ACID, native vectors") satisfied by more
  than one engine?
- Does the scope (portfolio, local-first, fewer than 1M vectors) need a
  distributed engine, or would a single-node store be enough?
- What is the cost of operating a managed cloud cluster versus running
  the same patterns locally?

## Decision

Adopt **Postgres 16 + the pgvector 0.7+ extension** as the single engine for
every table in the system (alerts, playbooks, episodic memory, LTM, audit).

No second engine. No external vector DB. No managed cloud service.

## Rationale

1. **Same unified-substrate thesis, different engine.** Postgres +
   pgvector combines relational SQL and vector search in a single engine
   with strict ACID. The key architectural claim — "avoid two engines you
   have to keep in sync" — holds for any engine that supports both, and
   Postgres + pgvector is one of them.
2. **Strict ACID, same guarantees that matter here.** Postgres offers
   serializable transactions. At the project's target size there is no
   functional gap with a distributed engine.
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

| Alternative | Why it was not selected for this project |
| --- | --- |
| **TiDB Cloud** | Strong architectural fit; the horizontal-scale and global-replica advantages do not yet apply at the portfolio scope, and a managed cloud account adds friction for someone cloning the repo. A natural future migration target if the corpus outgrows a single node. |
| **CockroachDB** | The single-node setup that fits this scope does not justify cluster operations; benefits appear with multi-region writes that are out of scope. |
| **Postgres + Pinecone** | Breaks the *single-substrate* thesis: two engines to keep consistent, two APIs, extra synchronisation. Increases failure surface and adds cloud cost. |
| **Postgres + Qdrant / Weaviate** | Same shape as Pinecone — two engines, two query languages. The "semantic-transactional join" that is the central pattern of Ch. 3 disappears. |
| **DuckDB + vector extension** | Excellent for analytics; not designed as an OLTP system with concurrency or transactional immutable auditing. |

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
