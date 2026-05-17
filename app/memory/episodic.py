"""Episodic memory: conversation turns with embeddings."""
import json
from typing import Optional

from . import db


def record_turn(
    session_id: str,
    analyst_id: str,
    role: str,
    content: str,
    embedding=None,
    metadata: Optional[dict] = None,
) -> int:
    meta = json.dumps(metadata or {})
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO episodic_memory
                  (session_id, analyst_id, role, content, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING turn_id;
                """,
                (session_id, analyst_id, role, content, embedding, meta),
            )
            return cur.fetchone()[0]
    finally:
        db.release_conn(conn)


def recent_turns(session_id: str, limit: int = 10):
    """Last N turns in ascending chronological order (ready to feed the LLM)."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT turn_id, role, content, created_at
                FROM episodic_memory
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        rows.reverse()
        return [
            {
                "turn_id": r[0],
                "role": r[1],
                "content": r[2],
                "created_at": r[3].isoformat(),
            }
            for r in rows
        ]
    finally:
        db.release_conn(conn)


def search_session(session_id: str, query_embedding, limit: int = 3):
    """Semantic search inside a single session ("what did we say about X")."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT turn_id, role, content, created_at,
                       embedding <=> %s::vector AS distance
                FROM episodic_memory
                WHERE session_id = %s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (query_embedding, session_id, query_embedding, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "turn_id": r[0],
                "role": r[1],
                "content": r[2],
                "created_at": r[3].isoformat(),
                "distance": float(r[4]),
            }
            for r in rows
        ]
    finally:
        db.release_conn(conn)
