"""
Retrieval patterns from Chapter 3 of the reference book:

- ``search_playbooks``         : pure RAG over the playbook chunk corpus.
- ``search_similar_alerts``    : semantic-transactional join — vector
                                 similarity plus SQL filters in a single
                                 query, a single transaction, a single
                                 execution plan.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from sentence_transformers import SentenceTransformer

from . import db

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("[API] loading embedding model")
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def embed(text: str):
    return get_model().encode(text, normalize_embeddings=True)


@contextmanager
def cursor():
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        db.release_conn(conn)


def search_playbooks(query_text: str, limit: int = 3):
    """Pure RAG: vector similarity over the playbook chunks."""
    qvec = embed(query_text)
    with cursor() as cur:
        cur.execute(
            """
            SELECT chunk_id, playbook_id, chunk_index, title, content,
                   embedding <=> %s::vector AS distance
            FROM playbook_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (qvec, qvec, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "chunk_id": str(r[0]),
            "playbook_id": r[1],
            "chunk_index": r[2],
            "title": r[3],
            "content": r[4],
            "distance": float(r[5]),
        }
        for r in rows
    ]


def search_similar_alerts(
    query_text: str,
    severities: Optional[list[str]] = None,
    since: Optional[datetime] = None,
    limit: int = 5,
):
    """
    Semantic-transactional join: vector similarity combined with SQL
    filters in a single query. This is the headline pattern of
    Chapter 3 — the one that disappears the moment vectors live in a
    separate engine from the transactional facts.
    """
    qvec = embed(query_text)
    sql = """
        SELECT alert_id, severity, category, source_ip::text,
               raw_text, detected_at,
               embedding <=> %s::vector AS distance
        FROM alerts
        WHERE embedding IS NOT NULL
    """
    params: list = [qvec]

    if severities:
        sql += " AND severity = ANY(%s)"
        params.append(severities)
    if since:
        sql += " AND detected_at >= %s"
        params.append(since)

    sql += " ORDER BY embedding <=> %s::vector LIMIT %s;"
    params.extend([qvec, limit])

    with cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "alert_id": str(r[0]),
            "severity": r[1],
            "category": r[2],
            "source_ip": r[3],
            "raw_text": r[4],
            "detected_at": r[5].isoformat(),
            "distance": float(r[6]),
        }
        for r in rows
    ]
