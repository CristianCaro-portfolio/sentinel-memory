"""sentinel-memory API — Act 2: RAG + semantic-transactional join."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.memory import db, retrieval


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    retrieval.get_model()  # eager-load the embedding model
    yield
    db.close_pool()


app = FastAPI(title="sentinel-memory", version="0.2.0", lifespan=lifespan)


class PlaybookQuery(BaseModel):
    query: str = Field(..., examples=["Multiple failed logins from one IP"])
    limit: int = 3


class IncidentQuery(BaseModel):
    query: str = Field(..., examples=["SSH brute force attempt"])
    severities: Optional[list[str]] = Field(default=None, examples=[["high", "critical"]])
    hours_back: Optional[int] = Field(default=None, examples=[24])
    limit: int = 5


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
            req.query,
            severities=req.severities,
            since=since,
            limit=req.limit,
        )
    }
