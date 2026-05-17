"""Embedding worker — CDC with LISTEN / NOTIFY.

Consumes new or invalidated alerts and writes their embedding back into
the row. The FastAPI service does not know this worker exists; the only
contract between them is the ``alerts_changed`` Postgres channel and the
``alerts.embedding`` column.

Architecture note: the wait loop uses ``select.select()`` with a 60-second
timeout. The connection sits IDLE between events — Postgres pushes the
notification when an event happens (latency typically < 5 ms). This is
true push, not disguised polling.
"""
import os
import select

import psycopg2
import psycopg2.extensions
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def connect():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "sentinel"),
        user=os.getenv("DB_USER", "sentinel_user"),
        password=os.getenv("DB_PASSWORD", "sentinel_password"),
    )
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    register_vector(conn)
    return conn


def embed_one(cur, model, alert_id: str) -> bool:
    cur.execute(
        "SELECT raw_text FROM alerts WHERE alert_id = %s AND embedding IS NULL;",
        (alert_id,),
    )
    row = cur.fetchone()
    if not row:
        return False
    vec = model.encode(row[0], normalize_embeddings=True)
    cur.execute(
        "UPDATE alerts SET embedding = %s WHERE alert_id = %s;",
        (vec, alert_id),
    )
    return True


def backfill(cur, model) -> int:
    cur.execute("SELECT alert_id FROM alerts WHERE embedding IS NULL;")
    ids = [r[0] for r in cur.fetchall()]
    count = 0
    for aid in ids:
        if embed_one(cur, model, str(aid)):
            print(f"[worker] backfill embedded {aid}", flush=True)
            count += 1
    return count


def main() -> None:
    print(f"[worker] loading {MODEL_NAME}", flush=True)
    model = SentenceTransformer(MODEL_NAME)
    conn = connect()
    cur = conn.cursor()

    n = backfill(cur, model)
    print(f"[worker] backfill done: {n} alerts", flush=True)

    cur.execute("LISTEN alerts_changed;")
    print("[worker] listening on channel 'alerts_changed'", flush=True)

    while True:
        if select.select([conn], [], [], 60) == ([], [], []):
            continue
        conn.poll()
        while conn.notifies:
            note = conn.notifies.pop(0)
            alert_id = note.payload
            print(f"[worker] NOTIFY received for {alert_id}", flush=True)
            try:
                if embed_one(cur, model, alert_id):
                    print(f"[worker] embedded {alert_id}", flush=True)
            except Exception as e:
                print(f"[worker] error on {alert_id}: {e}", flush=True)


if __name__ == "__main__":
    main()
