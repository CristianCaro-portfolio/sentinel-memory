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

## Temporal consistency + CDC (Act 4)

Two architecturally meaningful capabilities run on the same Postgres:

| Capability | Pattern | Real-world use |
| --- | --- | --- |
| **Temporal consistency** | SCD2 + bitemporal lookup | "What did this alert look like when we decided to close it?" |
| **CDC via LISTEN / NOTIFY** | Push, not polling | New alerts get embedded automatically without the API knowing the worker exists. |

### How it is wired

- `alerts_history` is an SCD2 table that the `capture_alert_change`
  trigger fills on every meaningful UPDATE (`severity`, `status` or
  `raw_text` change).
- `notify_alert_needs_embedding` fires `pg_notify('alerts_changed', ...)`
  on inserts/updates that leave `embedding IS NULL`.
- `invalidate_embedding_on_text_change` drops the embedding whenever
  `raw_text` is rewritten, which in turn fires the NOTIFY trigger and
  the worker re-embeds the row.
- `workers/embedding_worker.py` runs in its own container, does a
  one-shot backfill on boot, then `LISTEN alerts_changed`. The API and
  the worker never talk to each other directly — the only contract is
  the Postgres channel and the `alerts.embedding` column.

### Demo 1 — CDC: insert an alert, watch it embed itself

In one terminal, tail the worker:

```bash
docker compose logs -f embedding_worker
```

In another, post a new alert:

```bash
curl -s -X POST http://localhost:8000/alerts \
  -H "Content-Type: application/json" \
  -d '{
        "source_ip": "45.61.23.99",
        "severity": "high",
        "category": "reconnaissance",
        "raw_text": "Nmap scan detected: 65000 ports probed across DMZ in 90 seconds from 45.61.23.99"
      }' | jq
```

Within a second the worker logs:

```
[worker] NOTIFY received for <alert_id>
[worker] embedded <alert_id>
```

The new row now shows up in semantic search without anyone touching the
API or the worker manually:

```bash
curl -s -X POST http://localhost:8000/search/similar-incidents \
  -H "Content-Type: application/json" \
  -d '{"query":"port scanning my perimeter","limit":2}' | jq '.results[].raw_text'
```

### Demo 2 — Time travel for forensics

```bash
ALERT_ID=<the id you just created>
T0=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")
sleep 2

curl -s -X PATCH http://localhost:8000/alerts/$ALERT_ID \
  -H "Content-Type: application/json" \
  -d '{"severity":"critical"}'

sleep 2

curl -s -X PATCH http://localhost:8000/alerts/$ALERT_ID \
  -H "Content-Type: application/json" \
  -d '{"status":"investigating"}'

curl -s http://localhost:8000/alerts/$ALERT_ID/history | jq
curl -s "http://localhost:8000/alerts/$ALERT_ID/as-of?at=${T0//+/%2B}" | jq
```

The `as-of` query returns the alert exactly as it existed at `T0`
(`severity=high`, `status=open`) — backed by triggers the application
cannot bypass.

---

## Governance: audit + RBAC + living index (Act 5)

This is the layer that takes the project from "prototype" to "consumable
by an organisation".

| Capability | Where it lives |
| --- | --- |
| **Universal audit log** | `app/governance/audit.py` — one helper, called on every gated handler. Rows go to the immutable `audit_log` table. |
| **Role-based access control** | `app/governance/rbac.py` — the analyst role lives in LTM, a FastAPI dependency enforces it. |
| **Living index** | `feedback` table + `feedback_scores` view + hybrid scoring in `app/memory/retrieval.py` (`final_score = distance − feedback_weight × avg_rating`). |

All write paths now require the `X-Analyst-Id` header. Role permissions:

| Role | Permissions |
| --- | --- |
| `auditor` | `read_audit` |
| `analyst` | `chat`, `search`, `create_alert`, `patch_alert`, `submit_feedback` |
| `senior_analyst` | everything above + `read_audit` |

Seed roles: `cristian` = `senior_analyst`, `audit_bot` = `auditor`.

### Demo 1 — Universal audit log

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Analyst-Id: cristian" \
  -d '{"analyst_id":"cristian","message":"What should I do about a brute force?"}' \
  | jq '{turn_id, latency_ms}'

curl -s -H "X-Analyst-Id: cristian" 'http://localhost:8000/audit?limit=5' | jq
```

Every gated handler leaves `principal`, `operation`, `query_text`,
`retrieved_ids`, `latency_ms` — regulatory traceability with a single
helper, not boilerplate in every endpoint.

### Demo 2 — RBAC blocks the auditor

```bash
# auditor can NOT chat
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Analyst-Id: audit_bot" \
  -d '{"analyst_id":"audit_bot","message":"hello"}'
# → 403 {"detail":"role 'auditor' lacks permission 'chat'"}

# but it CAN read the audit log
curl -s -H "X-Analyst-Id: audit_bot" 'http://localhost:8000/audit?limit=3' | jq
```

### Demo 3 — Living index re-weights from analyst feedback

```bash
# Search before any feedback
curl -s -X POST http://localhost:8000/search/playbooks \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"SSH brute force","limit":3}' \
  | jq '.results[] | {title, distance, feedback_score, final_score}'

# Penalise an irrelevant chunk
curl -s -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"analyst_id":"cristian","target_kind":"playbook_chunk",
       "target_id":"<chunk_id>","rating":-1,
       "note":"this is exfiltration, not brute force"}'

# Re-search — distance is unchanged, final_score moved
curl -s -X POST http://localhost:8000/search/playbooks \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"SSH brute force","limit":3}' \
  | jq '.results[] | {title, distance, feedback_score, final_score}'
```

The pure cosine `distance` does not change, but `feedback_score` falls
to `−1.0` for the penalised row, and `final_score = distance − 0.2 ×
feedback_score` moves it down the ranking. No retraining required.

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
├── db-init/                       # SQL bootstrap (extensions, schema, seed, temporal+CDC)
├── app/                           # FastAPI service
│   ├── main.py                    # endpoints + Pydantic models + lifespan
│   ├── governance/
│   │   ├── audit.py               # immutable audit-log helper
│   │   └── rbac.py                # role-based dependency
│   ├── llm/
│   │   └── claude.py              # thin wrapper around the Anthropic API
│   └── memory/
│       ├── db.py                  # psycopg2 pool + pgvector type registration
│       ├── retrieval.py           # hybrid scoring (vector + feedback) RAG queries
│       ├── episodic.py            # per-session conversation turns
│       └── ltm.py                 # long-term analyst preferences
├── scripts/
│   └── embed_seed.py              # one-shot job to embed the seed rows
├── workers/
│   └── embedding_worker.py        # CDC consumer (LISTEN/NOTIFY) → backfill + embed-on-event
├── data/
│   ├── findings_sample.jsonl      # Simulated CDC feed
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
- [x] **Act 4** — Temporal consistency (SCD2) + CDC worker (LISTEN/NOTIFY)
- [x] **Act 5** — Embedded governance: audit + RBAC + living index

---

## License

MIT — see `LICENSE` (to be added).
