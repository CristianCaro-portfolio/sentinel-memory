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
docker compose up -d --build
```

This brings up two containers:

| Container           | Role                                                  | Port |
| ------------------- | ----------------------------------------------------- | ---- |
| `sentinel_postgres` | Postgres 16 with the `pgvector` extension preloaded   | 5432 |
| `sentinel_api`      | FastAPI service exposing RAG + semantic-transactional join | 8000 |

The API image pre-bakes the `all-MiniLM-L6-v2` model, so the first
`docker compose build` takes a few minutes but every subsequent start
is fast and works offline.

### One-time: embed the seed data

The seed rows (alerts and playbook chunks) ship with `embedding IS NULL`.
Generate the vectors once:

```bash
docker exec -it sentinel_api python scripts/embed_seed.py
```

Expected output:

```
[embed_seed] loading model: sentence-transformers/all-MiniLM-L6-v2
[embed_seed] 4 playbook chunks to embed
[embed_seed] 6 alerts to embed
[embed_seed] done
```

---

## Verifying the database

```bash
docker exec -it sentinel_postgres psql -U sentinel_user -d sentinel
```

Then, inside `psql`:

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

## Using the API

Open the auto-generated docs: <http://localhost:8000/docs>.

### Health

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

### `POST /search/playbooks` — pure RAG

Retrieves the most semantically similar remediation chunks.

```bash
curl -s -X POST http://localhost:8000/search/playbooks \
  -H 'Content-Type: application/json' \
  -d '{"query":"Multiple failed SSH logins from a single IP","limit":2}'
```

### `POST /search/similar-incidents` — semantic-transactional join

This is the headline pattern: **vector similarity + SQL filters in one
query, one transaction, one execution plan.** A two-engine stack
(Postgres + a separate vector DB) needs two round-trips and loses
atomicity and precision.

```bash
curl -s -X POST http://localhost:8000/search/similar-incidents \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "SSH brute force attempt",
        "severities": ["high","critical"],
        "hours_back": 24,
        "limit": 3
      }'
```

The query that runs under the hood:

```sql
SELECT alert_id, severity, category, source_ip, raw_text, detected_at,
       embedding <=> $1::vector AS distance   -- semantic ranking
FROM alerts
WHERE embedding IS NOT NULL
  AND severity = ANY($2::text[])              -- transactional filter
  AND detected_at >= $3                       -- transactional filter
ORDER BY embedding <=> $1::vector
LIMIT $4;
```

---

## Chat with memory (Act 3)

The `/chat` endpoint closes the agentic loop:

1. Loads the analyst's persistent preferences (LTM).
2. Recovers the latest turns from the current session (episodic memory).
3. Runs RAG over the playbook corpus.
4. Runs the semantic-transactional join over alerts **filtered by the
   analyst's LTM** (for example `severity_filter = ["high", "critical"]`).
5. Calls Claude with all that context as the system prompt and the
   session history as messages.
6. Stores both the user message and the assistant reply, each with its
   embedding, in `episodic_memory`.

Requires `ANTHROPIC_API_KEY` in `.env`. Default model:
`claude-haiku-4-5-20251001` (override with `CLAUDE_MODEL`).

### Turn 1 — opening question

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
        "analyst_id": "cristian",
        "message": "I am seeing 47 failed logins from a single IP in 4 minutes. What do I do?"
      }' | jq
```

The response includes a fresh `session_id`, a reply that cites a
playbook chunk such as `[PB-001-0]` and at least one `[alert:UUID8]`,
and the `applied_preferences` block confirming the LTM that was loaded.

### Turn 2 — the agent remembers

Use the **same** `session_id` from turn 1:

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
        "analyst_id": "cristian",
        "session_id": "<paste session_id here>",
        "message": "What if the IPs rotate? Same procedure?"
      }' | jq
```

Claude resolves "the IPs" to the brute force from turn 1 without you
repeating it. That is episodic memory working — and the difference
between a stateless chatbot and an agent.

### Turn 3 — modify LTM at runtime

```bash
curl -s -X POST http://localhost:8000/analyst/cristian/preferences \
  -H "Content-Type: application/json" \
  -d '{"key":"severity_filter","value":["critical"],"importance":0.95}'

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
        "analyst_id": "cristian",
        "message": "Which incidents similar to data exfiltration happened recently?"
      }' | jq '.citations.alerts'
```

Only `critical` alerts show up. The LTM changed retrieval behaviour
without any code change in the agent.

### Turn 4 — audit the whole session

```bash
curl -s http://localhost:8000/sessions/<session_id>/turns | jq '.turns[] | {role, content}'
```

Every turn is in the database with its embedding. Memory that survives
restarts and is queryable.

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
├── app/                           # FastAPI service
│   ├── main.py                    # endpoints + Pydantic models + lifespan
│   ├── llm/
│   │   └── claude.py              # thin wrapper around the Anthropic API
│   └── memory/
│       ├── db.py                  # psycopg2 pool + pgvector type registration
│       ├── retrieval.py           # RAG and semantic-transactional join queries
│       ├── episodic.py            # per-session conversation turns
│       └── ltm.py                 # long-term analyst preferences
├── scripts/
│   └── embed_seed.py              # one-shot job to embed the seed rows
├── workers/                       # Embedding worker (Act 4)
├── data/
│   ├── findings_sample.jsonl      # Simulated CDC feed (Act 4)
│   └── playbooks/                 # Markdown corpus for RAG
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .dockerignore
└── README.md
```

---

## Status

- [x] **Act 0** — Setup, ADR, schema design
- [x] **Act 1** — Foundation (Postgres + pgvector + seed)
- [x] **Act 2** — RAG + semantic-transactional join API
- [x] **Act 3** — Chat with episodic memory + LTM (Anthropic Claude)
- [ ] **Act 4** — Embedding worker + CDC-style ingest
- [ ] **Act 5** — Governance & observability hardening

---

## License

MIT — see `LICENSE` (to be added).
