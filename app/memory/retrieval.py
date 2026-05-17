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


# Living-index knob: weight given to analyst feedback (avg_rating in
# [-1, 1]) relative to pure cosine distance when computing final_score.
# 0.0 disables feedback; 0.5+ lets feedback dominate (risky with little
# data); 0.2 is the working default.
FEEDBACK_WEIGHT = 0.2


def search_playbooks(query_text: str, limit: int = 3):
    """Hybrid RAG: vector distance fused with analyst feedback (living index)."""
    qvec = embed(query_text)
    with cursor() as cur:
        cur.execute(
            """
            SELECT pc.chunk_id, pc.playbook_id, pc.chunk_index, pc.title, pc.content,
                   (pc.embedding <=> %s::vector)              AS distance,
                   COALESCE(fs.avg_rating, 0)::real           AS feedback_score,
                   COALESCE(fs.n_ratings, 0)                  AS n_ratings,
                   (pc.embedding <=> %s::vector)
                     - (COALESCE(fs.avg_rating, 0)::real * %s) AS final_score
            FROM playbook_chunks pc
            LEFT JOIN feedback_scores fs
              ON fs.target_kind = 'playbook_chunk' AND fs.target_id = pc.chunk_id
            WHERE pc.embedding IS NOT NULL
            ORDER BY final_score
            LIMIT %s;
            """,
            (qvec, qvec, FEEDBACK_WEIGHT, limit),
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
            "feedback_score": float(r[6]),
            "n_ratings": int(r[7]),
            "final_score": float(r[8]),
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
    Semantic-transactional join with living-index scoring.

    Combines vector similarity, SQL filters (severity, time window) and
    analyst feedback in a single query — still one transaction, one
    execution plan. This is the headline pattern of Chapter 3 extended
    with the feedback layer of Chapter 4.
    """
    qvec = embed(query_text)
    sql = """
        SELECT a.alert_id, a.severity, a.category, a.source_ip::text,
               a.raw_text, a.detected_at,
               (a.embedding <=> %s::vector)              AS distance,
               COALESCE(fs.avg_rating, 0)::real          AS feedback_score,
               COALESCE(fs.n_ratings, 0)                 AS n_ratings,
               (a.embedding <=> %s::vector)
                 - (COALESCE(fs.avg_rating, 0)::real * %s) AS final_score
        FROM alerts a
        LEFT JOIN feedback_scores fs
          ON fs.target_kind = 'alert' AND fs.target_id = a.alert_id
        WHERE a.embedding IS NOT NULL
    """
    params: list = [qvec, qvec, FEEDBACK_WEIGHT]

    if severities:
        sql += " AND a.severity = ANY(%s)"
        params.append(severities)
    if since:
        sql += " AND a.detected_at >= %s"
        params.append(since)

    sql += " ORDER BY final_score LIMIT %s;"
    params.append(limit)

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
            "feedback_score": float(r[7]),
            "n_ratings": int(r[8]),
            "final_score": float(r[9]),
        }
        for r in rows
    ]
