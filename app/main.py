"""sentinel-memory API — Act 5: embedded governance, RBAC and living index."""
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.governance import audit, rbac
from app.llm import claude
from app.memory import db, episodic, ltm, retrieval


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    retrieval.get_model()  # eager-load the embedding model
    yield
    db.close_pool()


app = FastAPI(title="sentinel-memory", version="0.6.0", lifespan=lifespan)


# Static UI: served at /ui (the / root redirects to it for convenience).
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if _WEB_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")


@app.get("/", include_in_schema=False)
def _root_redirect():
    return RedirectResponse(url="/ui/")


class PlaybookQuery(BaseModel):
    query: str
    limit: int = 3


class IncidentQuery(BaseModel):
    query: str
    severities: Optional[list[str]] = None
    hours_back: Optional[int] = None
    limit: int = 5


class ChatRequest(BaseModel):
    analyst_id: str = Field(..., examples=["cristian"])
    session_id: Optional[str] = Field(
        default=None,
        description="If null a fresh session is generated and returned in the response.",
    )
    message: str


class LtmUpsert(BaseModel):
    key: str
    value: Any
    importance: float = 0.5


class AlertCreate(BaseModel):
    source_ip: str = Field(..., examples=["10.0.0.99"])
    severity: str
    category: str
    raw_text: str


class AlertPatch(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None


class FeedbackIn(BaseModel):
    analyst_id: str
    session_id: Optional[str] = None
    turn_id: Optional[int] = None
    target_kind: str = Field(..., examples=["playbook_chunk"])
    target_id: str
    rating: int = Field(..., ge=-1, le=1)
    note: Optional[str] = None


def _build_system_prompt(prefs, playbook_hits, alert_hits) -> str:
    parts = [
        "You are an AI assistant supporting a security analyst.",
        "Use the retrieved context to propose a concrete next action.",
        "Always cite sources: [PB-XXX-N] for playbook chunks, [alert:UUID8] for past incidents.",
        "Keep replies concise (4-8 sentences).",
        "",
        "## Analyst preferences (LTM)",
        json.dumps(prefs, indent=2) if prefs else "(none)",
        "",
        "## Relevant playbook chunks (RAG)",
    ]
    for h in playbook_hits:
        parts.append(f"[{h['playbook_id']}-{h['chunk_index']}] {h['title']}: {h['content']}")
    parts.append("")
    parts.append("## Similar past incidents (semantic-transactional join)")
    for h in alert_hits:
        parts.append(
            f"[alert:{h['alert_id'][:8]}] severity={h['severity']} "
            f"category={h['category']} ip={h['source_ip']}: {h['raw_text']}"
        )
    return "\n".join(parts)


@app.get("/health")
def health():
    with retrieval.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"status": "ok"}


@app.post("/search/playbooks")
def post_search_playbooks(
    req: PlaybookQuery,
    _: dict = Depends(rbac.require_permission("search")),
):
    return {"results": retrieval.search_playbooks(req.query, limit=req.limit)}


@app.post("/search/similar-incidents")
def post_search_incidents(
    req: IncidentQuery,
    _: dict = Depends(rbac.require_permission("search")),
):
    since = None
    if req.hours_back:
        since = datetime.now(timezone.utc) - timedelta(hours=req.hours_back)
    return {
        "results": retrieval.search_similar_alerts(
            req.query, severities=req.severities, since=since, limit=req.limit
        )
    }


@app.post("/chat")
def post_chat(
    req: ChatRequest,
    _: dict = Depends(rbac.require_permission("chat")),
):
    t0 = time.time()
    session_id = req.session_id or str(uuid.uuid4())

    prefs = ltm.get_ltm(req.analyst_id)
    severity_filter = prefs.get("severity_filter") if prefs else None

    qvec = retrieval.embed(req.message)

    playbook_hits = retrieval.search_playbooks(req.message, limit=3)
    alert_hits = retrieval.search_similar_alerts(
        req.message, severities=severity_filter, limit=3
    )
    history = episodic.recent_turns(session_id, limit=10)

    episodic.record_turn(
        session_id, req.analyst_id, "user", req.message,
        embedding=qvec, metadata={"client": "api"},
    )

    system_prompt = _build_system_prompt(prefs, playbook_hits, alert_hits)
    messages = [
        {"role": t["role"], "content": t["content"]}
        for t in history if t["role"] in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": req.message})

    reply = claude.complete(system_prompt, messages, max_tokens=1024)

    reply_vec = retrieval.embed(reply)
    assistant_turn_id = episodic.record_turn(
        session_id, req.analyst_id, "assistant", reply,
        embedding=reply_vec,
        metadata={
            "playbook_ids": [h["chunk_id"] for h in playbook_hits],
            "alert_ids": [h["alert_id"] for h in alert_hits],
        },
    )

    if severity_filter:
        ltm.touch_ltm(req.analyst_id, ["severity_filter"])

    latency_ms = int((time.time() - t0) * 1000)
    audit.log_audit(
        principal=req.analyst_id,
        operation="chat",
        query_text=req.message,
        retrieved_ids=[h["chunk_id"] for h in playbook_hits]
        + [h["alert_id"] for h in alert_hits],
        granted=True,
        latency_ms=latency_ms,
        metadata={"session_id": session_id, "turn_id": assistant_turn_id},
    )

    return {
        "session_id": session_id,
        "turn_id": assistant_turn_id,
        "reply": reply,
        "citations": {
            "playbooks": [
                {
                    "id": h["chunk_id"],
                    "title": h["title"],
                    "playbook_id": h["playbook_id"],
                    "final_score": h["final_score"],
                    "n_ratings": h["n_ratings"],
                }
                for h in playbook_hits
            ],
            "alerts": [
                {
                    "id": h["alert_id"],
                    "severity": h["severity"],
                    "summary": h["raw_text"][:80],
                    "final_score": h["final_score"],
                    "n_ratings": h["n_ratings"],
                }
                for h in alert_hits
            ],
        },
        "applied_preferences": prefs,
        "latency_ms": latency_ms,
    }


@app.get("/sessions/{session_id}/turns")
def get_session_turns(session_id: str):
    return {"turns": episodic.recent_turns(session_id, limit=50)}


@app.get("/analyst/{analyst_id}/preferences")
def get_preferences(analyst_id: str):
    return {"preferences": ltm.list_ltm(analyst_id)}


@app.post("/analyst/{analyst_id}/preferences")
def post_preferences(analyst_id: str, req: LtmUpsert):
    ltm.upsert_ltm(analyst_id, req.key, req.value, req.importance)
    return {"status": "ok", "preferences": ltm.list_ltm(analyst_id)}


@app.post("/alerts")
def post_alert(
    req: AlertCreate,
    _: dict = Depends(rbac.require_permission("create_alert")),
):
    """Insert an alert. The NOTIFY trigger wakes the worker so it embeds the row."""
    with retrieval.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alerts (source_ip, severity, category, raw_text)
            VALUES (%s::inet, %s, %s, %s)
            RETURNING alert_id, detected_at;
            """,
            (req.source_ip, req.severity, req.category, req.raw_text),
        )
        row = cur.fetchone()
    return {"alert_id": str(row[0]), "detected_at": row[1].isoformat()}


@app.patch("/alerts/{alert_id}")
def patch_alert(
    alert_id: str,
    req: AlertPatch,
    _: dict = Depends(rbac.require_permission("patch_alert")),
):
    """Update status or severity. The trigger captures the previous version into alerts_history."""
    sets, params = [], []
    if req.status is not None:
        sets.append("status = %s")
        params.append(req.status)
    if req.severity is not None:
        sets.append("severity = %s")
        params.append(req.severity)
    if not sets:
        raise HTTPException(status_code=400, detail="nothing to update")
    params.append(alert_id)
    sql = (
        f"UPDATE alerts SET {', '.join(sets)} WHERE alert_id = %s "
        f"RETURNING alert_id, status, severity, valid_from;"
    )
    with retrieval.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "alert_id": str(row[0]),
        "status": row[1],
        "severity": row[2],
        "valid_from": row[3].isoformat(),
    }


@app.get("/alerts/{alert_id}/as-of")
def get_alert_as_of(alert_id: str, at: datetime):
    """State of the alert as it existed at timestamp ``at`` (bitemporal lookup)."""
    with retrieval.cursor() as cur:
        cur.execute(
            """
            WITH versions AS (
              SELECT alert_id, severity, category, raw_text, status,
                     valid_from, NULL::timestamptz AS valid_to,
                     'current' AS src
              FROM alerts
              WHERE alert_id = %s AND valid_from <= %s
              UNION ALL
              SELECT alert_id, severity, category, raw_text, status,
                     valid_from, valid_to, 'history' AS src
              FROM alerts_history
              WHERE alert_id = %s AND valid_from <= %s AND valid_to > %s
            )
            SELECT * FROM versions ORDER BY valid_from DESC LIMIT 1;
            """,
            (alert_id, at, alert_id, at, at),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="no version at that timestamp")
    return {
        "alert_id": str(row[0]),
        "severity": row[1],
        "category": row[2],
        "raw_text": row[3],
        "status": row[4],
        "valid_from": row[5].isoformat(),
        "valid_to": row[6].isoformat() if row[6] else None,
        "source_table": row[7],
    }


@app.get("/alerts/{alert_id}/history")
def get_alert_history(alert_id: str):
    """Full version history for an alert (current + every captured change)."""
    with retrieval.cursor() as cur:
        cur.execute(
            """
            SELECT severity, status, valid_from, valid_to, 'history' AS src
            FROM alerts_history WHERE alert_id = %s
            UNION ALL
            SELECT severity, status, valid_from, NULL::timestamptz, 'current'
            FROM alerts WHERE alert_id = %s
            ORDER BY valid_from DESC;
            """,
            (alert_id, alert_id),
        )
        rows = cur.fetchall()
    return {
        "history": [
            {
                "severity": r[0],
                "status": r[1],
                "valid_from": r[2].isoformat(),
                "valid_to": r[3].isoformat() if r[3] else None,
                "source": r[4],
            }
            for r in rows
        ]
    }


@app.post("/feedback")
def post_feedback(
    req: FeedbackIn,
    _: dict = Depends(rbac.require_permission("submit_feedback")),
):
    """Record an analyst rating that feeds back into ``final_score``."""
    with retrieval.cursor() as cur:
        cur.execute(
            """
            INSERT INTO feedback
              (analyst_id, session_id, turn_id, target_kind, target_id, rating, note)
            VALUES (%s, %s, %s, %s, %s::uuid, %s, %s)
            RETURNING feedback_id;
            """,
            (
                req.analyst_id,
                req.session_id,
                req.turn_id,
                req.target_kind,
                req.target_id,
                req.rating,
                req.note,
            ),
        )
        fid = cur.fetchone()[0]
    audit.log_audit(
        principal=req.analyst_id,
        operation="submit_feedback",
        query_text=None,
        retrieved_ids=[req.target_id],
        granted=True,
        metadata={
            "rating": req.rating,
            "kind": req.target_kind,
            "feedback_id": fid,
        },
    )
    return {"feedback_id": fid, "status": "recorded"}


@app.get("/audit")
def get_audit(
    limit: int = 20,
    _: dict = Depends(rbac.require_permission("read_audit")),
):
    """Read the most recent audit events (paged by ``limit``)."""
    with retrieval.cursor() as cur:
        # Cast retrieved_ids to text[] so psycopg2 unpacks it into a Python list.
        # (uuid[] decoding is shadowed by the pgvector type registration in this pool.)
        cur.execute(
            """
            SELECT event_id, occurred_at, principal, operation,
                   query_text, retrieved_ids::text[],
                   granted, latency_ms, metadata
            FROM audit_log
            ORDER BY event_id DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return {
        "events": [
            {
                "event_id": r[0],
                "occurred_at": r[1].isoformat(),
                "principal": r[2],
                "operation": r[3],
                "query": r[4],
                "retrieved_ids": list(r[5] or []),
                "granted": r[6],
                "latency_ms": r[7],
                "metadata": r[8],
            }
            for r in rows
        ]
    }
