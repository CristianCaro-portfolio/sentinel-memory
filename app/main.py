"""sentinel-memory API — Act 3: chat with episodic memory + LTM."""
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.llm import claude
from app.memory import db, episodic, ltm, retrieval


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    retrieval.get_model()  # eager-load the embedding model
    yield
    db.close_pool()


app = FastAPI(title="sentinel-memory", version="0.3.0", lifespan=lifespan)


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
def post_search_playbooks(req: PlaybookQuery):
    return {"results": retrieval.search_playbooks(req.query, limit=req.limit)}


@app.post("/search/similar-incidents")
def post_search_incidents(req: IncidentQuery):
    since = None
    if req.hours_back:
        since = datetime.now(timezone.utc) - timedelta(hours=req.hours_back)
    return {
        "results": retrieval.search_similar_alerts(
            req.query, severities=req.severities, since=since, limit=req.limit
        )
    }


@app.post("/chat")
def post_chat(req: ChatRequest):
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
    episodic.record_turn(
        session_id, req.analyst_id, "assistant", reply,
        embedding=reply_vec,
        metadata={
            "playbook_ids": [h["chunk_id"] for h in playbook_hits],
            "alert_ids": [h["alert_id"] for h in alert_hits],
        },
    )

    if severity_filter:
        ltm.touch_ltm(req.analyst_id, ["severity_filter"])

    return {
        "session_id": session_id,
        "reply": reply,
        "citations": {
            "playbooks": [
                {
                    "id": h["chunk_id"],
                    "title": h["title"],
                    "playbook_id": h["playbook_id"],
                }
                for h in playbook_hits
            ],
            "alerts": [
                {
                    "id": h["alert_id"],
                    "severity": h["severity"],
                    "summary": h["raw_text"][:80],
                }
                for h in alert_hits
            ],
        },
        "applied_preferences": prefs,
    }


@app.get("/sessions/{session_id}/turns")
def get_session_turns(session_id: str):
    return {"turns": episodic.recent_turns(session_id, limit=50)}


@app.get("/analyst/{analyst_id}/preferences")
def get_preferences(analyst_id: str):
    return {"preferences": ltm.get_ltm(analyst_id)}


@app.post("/analyst/{analyst_id}/preferences")
def post_preferences(analyst_id: str, req: LtmUpsert):
    ltm.upsert_ltm(analyst_id, req.key, req.value, req.importance)
    return {"status": "ok", "preferences": ltm.get_ltm(analyst_id)}
