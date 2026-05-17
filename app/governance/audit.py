"""Helper that writes immutable rows to ``audit_log``.

The table itself enforces immutability with triggers (see
``db-init/02_schema.sql``). This module exists so that handlers can
record an audit event with one call and consistent metadata.
"""
import json
from typing import Optional

from app.memory import db


def log_audit(
    principal: str,
    operation: str,
    *,
    query_text: Optional[str] = None,
    retrieved_ids: Optional[list[str]] = None,
    granted: bool = True,
    latency_ms: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    meta = json.dumps(metadata or {})
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log
                  (principal, operation, query_text, retrieved_ids,
                   granted, latency_ms, metadata)
                VALUES (%s, %s, %s, %s::uuid[], %s, %s, %s::jsonb);
                """,
                (
                    principal,
                    operation,
                    query_text,
                    retrieved_ids,
                    granted,
                    latency_ms,
                    meta,
                ),
            )
    finally:
        db.release_conn(conn)
