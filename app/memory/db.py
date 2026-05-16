"""Postgres connection pool with support for the pgvector type."""
import os
from psycopg2.pool import SimpleConnectionPool
from pgvector.psycopg2 import register_vector

_pool: SimpleConnectionPool | None = None


def init_pool() -> None:
    global _pool
    _pool = SimpleConnectionPool(
        minconn=1, maxconn=10,
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "sentinel"),
        user=os.getenv("DB_USER", "sentinel_user"),
        password=os.getenv("DB_PASSWORD", "sentinel_password"),
    )
    # Register the pgvector type with psycopg2 (process-wide).
    conn = _pool.getconn()
    try:
        register_vector(conn)
    finally:
        _pool.putconn(conn)
    print(f"[API] pool created against {os.getenv('DB_HOST','postgres')}")


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
    print("[API] pool closed")


def get_conn():
    return _pool.getconn()


def release_conn(conn):
    _pool.putconn(conn)
