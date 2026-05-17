-- ==========================================================
-- feedback: analyst ratings on playbook chunks and alerts
-- ==========================================================
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id   bigserial PRIMARY KEY,
    analyst_id    text NOT NULL,
    session_id    uuid,
    turn_id       bigint,
    target_kind   text NOT NULL CHECK (target_kind IN ('alert','playbook_chunk')),
    target_id     uuid NOT NULL,
    rating        smallint NOT NULL CHECK (rating BETWEEN -1 AND 1),
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_target  ON feedback (target_kind, target_id);
CREATE INDEX IF NOT EXISTS feedback_analyst ON feedback (analyst_id, created_at);

-- Aggregated view used by the hybrid scoring in app/memory/retrieval.py
CREATE OR REPLACE VIEW feedback_scores AS
SELECT target_kind,
       target_id,
       AVG(rating)::real AS avg_rating,
       COUNT(*)::int     AS n_ratings
FROM feedback
GROUP BY target_kind, target_id;

-- ==========================================================
-- Roles for the simulated RBAC. Role is just another LTM key.
-- ==========================================================
INSERT INTO ltm (analyst_id, key, value, importance) VALUES
  ('cristian',  'role', '"senior_analyst"'::jsonb, 1.0),
  ('audit_bot', 'role', '"auditor"'::jsonb,        1.0)
ON CONFLICT (analyst_id, key) DO UPDATE
SET value      = EXCLUDED.value,
    importance = EXCLUDED.importance;
