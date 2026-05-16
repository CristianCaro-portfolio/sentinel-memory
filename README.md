# sentinel-memory

Memory layer for an agentic security analyst.
Implements RAG, episodic memory, long-term memory, temporal consistency
and immutable audit log — all on a single **Postgres + pgvector** substrate.

> Why a single substrate (and not TiDB / Pinecone / Qdrant)?
> See [`docs/adr/001-postgres-pgvector-vs-tidb.md`](docs/adr/001-postgres-pgvector-vs-tidb.md).

---

## Quick start

```bash
cp .env.example .env
docker compose up -d
docker exec -it sentinel_postgres psql -U sentinel_user -d sentinel
```

Once inside `psql`, verify the stack is healthy:

```sql
-- pgvector is installed
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

-- the five tables exist
\dt

-- seed data is loaded
SELECT count(*) AS alerts        FROM alerts;
SELECT count(*) AS playbooks     FROM playbook_chunks;
SELECT count(*) AS ltm_prefs     FROM ltm;
SELECT count(*) AS audit_events  FROM audit_log;
```

You should see 6 alerts, 4 playbook chunks, 4 LTM rows and 1 audit event.

### Smoke test: the audit log is really immutable

```sql
-- This must fail with "audit_log is immutable (...)"
UPDATE audit_log SET granted = false WHERE event_id = 1;
DELETE FROM audit_log WHERE event_id = 1;
```

If both statements raise an exception, immutability is wired correctly.

---

## Architecture

- High-level container diagram: [`docs/architecture/c4-container.mmd`](docs/architecture/c4-container.mmd)
- Architecture Decision Records: [`docs/adr/`](docs/adr/)

### The five tables, mapped to the patterns from the reference book

| Table               | Pattern                                  | Purpose                                                        |
| ------------------- | ---------------------------------------- | -------------------------------------------------------------- |
| `alerts`            | Semantic–transactional join (Ch. 3)      | Facts + embeddings in one row. SQL filter + ANN in one query.  |
| `playbook_chunks`   | RAG (Ch. 3)                              | Chunked remediation corpus retrieved by similarity.            |
| `episodic_memory`   | Episodic memory (Ch. 1, 3)               | Per-session conversation history (resume where you left off).  |
| `ltm`               | Long-term memory (Ch. 1, 3)              | Persistent analyst preferences (filters, thresholds, format).  |
| `audit_log`         | Embedded governance (Ch. 4)              | Immutable record of who asked what — enforced by triggers.     |

---

## Project layout

```
sentinel-memory/
├── docs/
│   ├── adr/                       # Architecture Decision Records
│   └── architecture/              # C4 diagrams (Mermaid + rendered SVG)
├── db-init/                       # SQL bootstrap (extensions, schema, seed)
├── app/                           # FastAPI service (Act 2+)
├── workers/                       # Embedding worker (Act 4)
├── data/
│   ├── findings_sample.jsonl      # Simulated CDC feed (Act 4)
│   └── playbooks/                 # Markdown corpus for RAG
├── tests/
├── docker-compose.yml
├── .env.example
├── .dockerignore
└── README.md
```

---

## Status

- [x] **Act 0** — Setup, ADR, schema design
- [x] **Act 1** — Foundation (Postgres + pgvector + seed)
- [ ] **Act 2** — FastAPI service: read paths
- [ ] **Act 3** — Episodic + LTM memory APIs
- [ ] **Act 4** — Embedding worker + CDC-style ingest
- [ ] **Act 5** — Governance & observability hardening

---

## License

MIT — see `LICENSE` (to be added).
