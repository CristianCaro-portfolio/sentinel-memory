"""Long-term memory: persistent analyst preferences."""
import json

from . import db


def get_ltm(analyst_id: str) -> dict:
    """Return every preference as {key: value} ordered by importance DESC."""
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT key, value FROM ltm
                WHERE analyst_id = %s
                ORDER BY importance DESC;
                """,
                (analyst_id,),
            )
            rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        db.release_conn(conn)


def touch_ltm(analyst_id: str, keys: list[str]) -> None:
    """Update last_used_at for the preferences that were actually consulted."""
    if not keys:
        return
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ltm SET last_used_at = now()
                WHERE analyst_id = %s AND key = ANY(%s);
                """,
                (analyst_id, keys),
            )
    finally:
        db.release_conn(conn)


def upsert_ltm(analyst_id: str, key: str, value, importance: float = 0.5) -> None:
    """Insert or update a single preference key for an analyst."""
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ltm (analyst_id, key, value, importance)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (analyst_id, key) DO UPDATE
                SET value = EXCLUDED.value,
                    importance = EXCLUDED.importance,
                    last_used_at = now();
                """,
                (analyst_id, key, json.dumps(value), importance),
            )
    finally:
        db.release_conn(conn)
