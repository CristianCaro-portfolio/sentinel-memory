"""One-shot job: generate embeddings for any seed rows that do not have them yet.

Run inside the api container:

    docker exec sentinel_api python scripts/embed_seed.py
"""
import os

import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main() -> None:
    print(f"[embed_seed] loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "sentinel"),
        user=os.getenv("DB_USER", "sentinel_user"),
        password=os.getenv("DB_PASSWORD", "sentinel_password"),
    )
    register_vector(conn)

    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_id, title || E'\\n' || content "
            "FROM playbook_chunks WHERE embedding IS NULL;"
        )
        rows = cur.fetchall()
        print(f"[embed_seed] {len(rows)} playbook chunks to embed")
        for chunk_id, text in rows:
            vec = model.encode(text, normalize_embeddings=True)
            cur.execute(
                "UPDATE playbook_chunks SET embedding=%s WHERE chunk_id=%s;",
                (vec, chunk_id),
            )

        cur.execute("SELECT alert_id, raw_text FROM alerts WHERE embedding IS NULL;")
        rows = cur.fetchall()
        print(f"[embed_seed] {len(rows)} alerts to embed")
        for alert_id, text in rows:
            vec = model.encode(text, normalize_embeddings=True)
            cur.execute(
                "UPDATE alerts SET embedding=%s WHERE alert_id=%s;",
                (vec, alert_id),
            )

    conn.close()
    print("[embed_seed] done")


if __name__ == "__main__":
    main()
