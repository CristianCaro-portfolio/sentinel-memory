# LinkedIn carousel — 8 slides

Copy-paste-ready for the post. The slides are short, the post body is longer
and lives in `linkedin-post.md` (below).

---

## Slide 1 — Hook

**Title**
> I built a memory layer for an AI security analyst.
> Vector search, episodic memory, audit, RBAC, live feedback.
> All on a single open-source engine.

**Subtitle**
> One substrate. Nine patterns. Zero lock-in.

**Suggested visual**: the C4 container diagram from the repo.

---

## Slide 2 — Why memory matters in agentic AI

**Title**: An agent isn't a chatbot — it remembers, reasons and adapts.

Most "agentic" stacks today look like this:

- Postgres for facts
- Pinecone for vectors
- Redis for session
- Snowflake for history
- Kafka for sync

**Five systems. Five inconsistencies to chase. Five things to audit.**

That's the problem the "Architectures for Agentic AI Data" book frames
beautifully — *memory should be infrastructure, not five systems duct-taped
together*.

---

## Slide 3 — The thesis I took from the book

**Title**: "Memory as infrastructure" (Stewart & Huang, O'Reilly 2025)

The book's core argument:

> Traditional architectures fail because they're built for **discrete
> transactional snapshots**, not for **continuously evolving state**.

The fix: **one ACID substrate** for facts, vectors, history, and audit.

That thesis is solid. The choice of engine is a project-scope call, not a
universal truth — and that's where my ADR comes in.

---

## Slide 4 — ADR-001: choosing the engine

**Title**: One ACID substrate ≠ one specific vendor.

The book illustrates the thesis with TiDB. I evaluated five candidates
before writing a line of code:

- **Postgres + pgvector** ← chosen for this scope
- TiDB Cloud — strong fit at scale, overkill for a portfolio project
- CockroachDB — same reasoning
- Postgres + Pinecone/Qdrant — breaks the single-substrate thesis
- DuckDB + vector ext — analytics-first, not OLTP

Postgres + pgvector wins on local-first ergonomics, 25 years of operational
maturity, and a clean migration path to a distributed engine if the corpus
outgrows a single node.

**The ADR is the deliverable here, not just the code.**

---

## Slide 5 — The signature query

**Title**: Semantic-transactional join

```sql
SELECT alert_id, severity, raw_text,
       embedding <=> $1::vector AS distance
FROM alerts
WHERE severity = ANY($2::text[])    -- SQL filter
  AND detected_at >= $3             -- SQL filter
ORDER BY embedding <=> $1::vector   -- vector ranking
LIMIT $4;
```

**One atomic query.** SQL filters + vector ranking in the same execution
plan.

In a split stack (Postgres + Pinecone) the equivalent needs 2–3 round-trips,
client-side re-ordering, and you lose atomicity.

---

## Slide 6 — Episodic memory + LTM

**Title**: The agent remembers across turns and across sessions.

**Episodic memory** — every turn stored with its embedding. The agent can
both *replay the chronology* and *semantically search* "what did we say
about X earlier in this session".

**LTM** — persistent analyst preferences (role, severity, ignored IPs)
**injected automatically as SQL filters** during retrieval.

LTM isn't a response cache — it's **declarative policy** the system applies
without a redeploy. Change one row, change the behaviour.

---

## Slide 7 — Embedded governance + living index

**Title**: What separates a prototype from a real system.

- **Immutable audit log** — every retrieval is captured; BEFORE
  UPDATE/DELETE triggers raise exceptions at the DB level.
- **RBAC** — the role lives in LTM, enforced as a FastAPI dependency. An
  auditor can read the log but cannot chat.
- **Living index** — analyst feedback (-1 / 0 / +1) accumulates in a
  view; hybrid retrieval blends it with vector distance.

**The system learns from human judgement without retraining the model.**
SQL re-ranks; weights live in data.

---

## Slide 8 — CTA

**Title**: What I take away from building this.

1. An ADR is worth more than the code it justifies.
2. Governance belongs in the substrate, not the application.
3. A unified substrate beats a fragmented stack at this scope — and gives
   you a clean migration path when scope changes.

**Bonus**: a vanilla-JS analyst console served by the same FastAPI process.
No npm, no framework, no excuses to skip a UI.

🔗 Repo: github.com/CristianCaro-portfolio/sentinel-memory
📄 Full pedagogical writeup + ADR + DEMO in the repo.

#DataArchitecture #DataEngineering #AgenticAI #Postgres #pgvector #RAG

---

## Production notes

- **Tool**: Canva → "Tech Carousel LinkedIn"
- **Size**: 1080 × 1350 px (portrait, optimised for LinkedIn)
- **Typography**: Inter or Roboto for prose, JetBrains Mono for SQL
- **Palette**: deep navy `#0d1117` background, blue `#58a6ff` accent
  (matches the analyst console)
- **Estimated production time**: 1–2 hours in Canva
- **Best posting window**: Tue–Thu, 9–11am ET

---

## Companion post body

```text
I built sentinel-memory: a unified memory layer for an AI security analyst
agent, on Postgres 16 + pgvector. Nine patterns, one substrate, zero lock-in.

The brief was simple: take the "memory as infrastructure" thesis from the
new O'Reilly book on agentic AI, and turn it into something you can run
locally with `docker compose up`.

What's inside:
• RAG over a remediation playbook corpus
• Semantic-transactional join (SQL filter + vector ranking, one query)
• Episodic memory + LTM driving retrieval as declarative policy
• SCD2 + AS OF TIMESTAMP for reproducible forensics
• Native CDC via LISTEN/NOTIFY (no Kafka)
• Immutable audit log + RBAC + living index from human feedback
• A minimalist analyst console served by the same FastAPI

The most interesting artifact for me isn't the code — it's ADR-001, where I
evaluated five substrates before picking pgvector for this scope.

Full repo + 5-min DEMO + pedagogical doc here:
👉 github.com/CristianCaro-portfolio/sentinel-memory

#DataArchitecture #AgenticAI #Postgres #pgvector
```
