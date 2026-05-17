# DEMO — sentinel-memory in 5 minutes

Walks through every pattern in a terminal session. Assumes
`docker compose up -d --build` is already running and the seed has been
embedded (`docker compose exec api python scripts/embed_seed.py`).

> Prefer clicking over typing? The same flows are available in the analyst
> console at **http://localhost:8000/ui/** — every step below has a matching
> tab in the UI.

## 1. Setup

```bash
export A=http://localhost:8000
```

## 2. Pattern 1 — RAG over playbooks

```bash
curl -sX POST $A/search/playbooks \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"someone hammering my SSH with bad passwords","limit":2}' | jq
```

**What you see**: the top hit is `PB-001 / Brute force login detection`,
even though the query never mentions "brute force" or "login". The
embedding captures the semantics.

> *In the UI*: **search** tab → playbooks column.

## 3. Pattern 2 — Semantic-transactional join

```bash
# No filter
curl -sX POST $A/search/similar-incidents \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"data exfiltration to weird domain","limit":3}' \
  | jq '.results[] | {severity, raw_text, distance}'

# With severity filter — only critical
curl -sX POST $A/search/similar-incidents \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"suspicious activity","severities":["critical"],"limit":3}' \
  | jq '.results[].severity'
```

**What you see**: in the second call every result is `critical`. The SQL
filter pruned the search space *before* the vector ranking, in **one atomic
query**.

> *In the UI*: **search** tab → similar incidents column → click the
> severity pills.

## 4. Pattern 3 — Episodic memory (multi-turn chat)

```bash
# Turn 1
SESSION=$(curl -sX POST $A/chat \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"analyst_id":"cristian","message":"Seeing 47 failed logins from a single IP. What now?"}' \
  | tee /tmp/r.json | jq -r '.session_id')
echo "session=$SESSION"
jq '.reply' /tmp/r.json

# Turn 2 — the agent REMEMBERS the context
curl -sX POST $A/chat \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d "{\"analyst_id\":\"cristian\",\"session_id\":\"$SESSION\",\"message\":\"And if the IPs rotate, do I follow the same procedure?\"}" \
  | jq '.reply'
```

**What you see**: turn 2 never says "brute force", yet Claude understands
that "the IPs" refer to the attack from turn 1. That is episodic memory.

> *In the UI*: **chat** tab. Each assistant turn shows its citations with
> live thumbs up/down buttons.

## 5. Pattern 4 — LTM as declarative policy

```bash
# Current state
curl -s $A/analyst/cristian/preferences | jq

# Change a preference
curl -sX POST $A/analyst/cristian/preferences \
  -H "Content-Type: application/json" \
  -d '{"key":"severity_filter","value":["critical"],"importance":0.95}' | jq

# Re-run the search — only critical now
curl -sX POST $A/chat \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"analyst_id":"cristian","message":"Show me similar exfiltration incidents."}' \
  | jq '.citations.alerts[].severity'
```

**What you see**: a single LTM row changed the retrieval behaviour with
**zero code change**. Policy lives in data.

> *In the UI*: **preferences** tab → upsert form. Re-run the chat in the
> **chat** tab.

## 6. Pattern 5 — Temporal consistency (forensics)

```bash
# Create a new alert (the worker embeds it automatically via LISTEN/NOTIFY)
ALERT_ID=$(curl -sX POST $A/alerts \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"source_ip":"45.61.23.99","severity":"high","category":"reconnaissance",
       "raw_text":"Nmap scan: 65000 ports probed across DMZ in 90 seconds"}' \
  | jq -r '.alert_id')

# Snapshot BEFORE we change anything
T0=$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ); sleep 2

# Change severity
curl -sX PATCH $A/alerts/$ALERT_ID \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"severity":"critical"}' > /dev/null

# Full history
curl -s $A/alerts/$ALERT_ID/history | jq

# Time travel: state at T0
curl -s "$A/alerts/$ALERT_ID/as-of?at=$T0" | jq '{severity, source_table}'
```

**What you see**: the final call returns `severity: "high"` — the state
from ~2 seconds ago, even though the alert is now `critical`. SCD2 in action.

> *In the UI*: **alerts** tab → click the alert → the SCD2 timeline appears
> on the right.

## 7. Pattern 6 — Audit log + RBAC + Living index

```bash
# Every retrieval and write is in the audit log
curl -s -H "X-Analyst-Id: cristian" "$A/audit?limit=5" \
  | jq '.events[] | {operation, principal, latency_ms}'

# The 'auditor' role cannot chat (403)
curl -sX POST $A/chat \
  -H "Content-Type: application/json" -H "X-Analyst-Id: audit_bot" \
  -d '{"analyst_id":"audit_bot","message":"hi"}' | jq

# But it can read the audit log
curl -s -H "X-Analyst-Id: audit_bot" "$A/audit?limit=3" | jq '.events[].operation'

# Feedback that re-weights the ranking
CHUNK_ID=$(curl -sX POST $A/search/playbooks \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"SSH brute force","limit":3}' | jq -r '.results[1].chunk_id')

curl -sX POST $A/feedback \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d "{\"analyst_id\":\"cristian\",\"target_kind\":\"playbook_chunk\",
       \"target_id\":\"$CHUNK_ID\",\"rating\":-1,
       \"note\":\"irrelevant for this query\"}" | jq

# Re-run the search — the punished chunk now has a worse final_score
curl -sX POST $A/search/playbooks \
  -H "Content-Type: application/json" -H "X-Analyst-Id: cristian" \
  -d '{"query":"SSH brute force","limit":3}' \
  | jq '.results[] | {title, distance, feedback_score, final_score}'
```

> *In the UI*: **audit log** tab (auto-refresh on demand) + the thumb
> buttons that live next to every citation and search result.

---

## What you just exercised in five minutes

- Semantic search over a domain corpus
- Transactional filters + vector ranking in one atomic query
- Cross-turn memory without re-stuffing the context
- Declarative policy that changes behaviour without redeploy
- Reproducible forensics via point-in-time queries
- Native CDC without Kafka
- DB-level immutable governance
- Role-based access control
- Human feedback that improves results without re-training a model

All on Postgres + pgvector. Zero additional services.
