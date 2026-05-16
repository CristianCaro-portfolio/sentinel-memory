-- =================================================
-- alerts: facts + vectors (semantic-transactional join)
-- =================================================
CREATE TABLE alerts (
    alert_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_ip    inet,
    severity     text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    category     text NOT NULL,
    raw_text     text NOT NULL,
    embedding    vector(384),                 -- MiniLM-L6-v2 dimension
    detected_at  timestamptz NOT NULL DEFAULT now(),
    valid_from   timestamptz NOT NULL DEFAULT now(),
    valid_to     timestamptz,                 -- NULL = currently valid
    status       text NOT NULL DEFAULT 'open'
);
CREATE INDEX alerts_emb_hnsw ON alerts USING hnsw (embedding vector_cosine_ops);
CREATE INDEX alerts_sev      ON alerts (severity);
CREATE INDEX alerts_valid    ON alerts (valid_from, valid_to);

-- =================================================
-- playbook_chunks: RAG corpus
-- =================================================
CREATE TABLE playbook_chunks (
    chunk_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    playbook_id  text NOT NULL,
    chunk_index  int  NOT NULL,
    title        text NOT NULL,
    content      text NOT NULL,
    embedding    vector(384),
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (playbook_id, chunk_index)
);
CREATE INDEX pb_emb_hnsw ON playbook_chunks USING hnsw (embedding vector_cosine_ops);

-- =================================================
-- episodic_memory: per-session conversation turns
-- =================================================
CREATE TABLE episodic_memory (
    turn_id      bigserial PRIMARY KEY,
    session_id   uuid NOT NULL,
    analyst_id   text NOT NULL,
    role         text NOT NULL CHECK (role IN ('user','assistant','tool')),
    content      text NOT NULL,
    embedding    vector(384),
    metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX epi_session   ON episodic_memory (session_id, created_at);
CREATE INDEX epi_emb_hnsw  ON episodic_memory USING hnsw (embedding vector_cosine_ops);

-- =================================================
-- ltm: persistent analyst preferences
-- =================================================
CREATE TABLE ltm (
    analyst_id    text NOT NULL,
    key           text NOT NULL,
    value         jsonb NOT NULL,
    importance    real NOT NULL DEFAULT 0.5,
    last_used_at  timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (analyst_id, key)
);

-- =================================================
-- audit_log: immutable, embedded governance (Ch. 4)
-- =================================================
CREATE TABLE audit_log (
    event_id       bigserial PRIMARY KEY,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    principal      text NOT NULL,
    operation      text NOT NULL,
    query_text     text,
    retrieved_ids  uuid[],
    granted        boolean NOT NULL,
    latency_ms     int,
    metadata       jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Enforce immutability: no one can UPDATE or DELETE the audit log
CREATE OR REPLACE FUNCTION audit_log_block_modify() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is immutable (event_id=%)', OLD.event_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
  BEFORE UPDATE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_block_modify();

CREATE TRIGGER audit_log_no_delete
  BEFORE DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_block_modify();
