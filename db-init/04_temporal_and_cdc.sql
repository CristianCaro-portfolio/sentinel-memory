-- ==========================================================
-- alerts_history: SCD2 table that backs temporal consistency
-- ==========================================================
CREATE TABLE IF NOT EXISTS alerts_history (
    history_id   bigserial PRIMARY KEY,
    alert_id     uuid NOT NULL,
    source_ip    inet,
    severity     text NOT NULL,
    category     text NOT NULL,
    raw_text     text NOT NULL,
    status       text NOT NULL,
    valid_from   timestamptz NOT NULL,
    valid_to     timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_history_lookup
    ON alerts_history (alert_id, valid_from, valid_to);

-- BEFORE UPDATE trigger: push the previous version into history and
-- reset valid_from on the NEW row.
CREATE OR REPLACE FUNCTION capture_alert_change() RETURNS trigger AS $$
BEGIN
    INSERT INTO alerts_history (
        alert_id, source_ip, severity, category, raw_text, status,
        valid_from, valid_to
    ) VALUES (
        OLD.alert_id, OLD.source_ip, OLD.severity, OLD.category,
        OLD.raw_text, OLD.status,
        OLD.valid_from, now()
    );
    NEW.valid_from := now();
    NEW.valid_to   := NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS alerts_capture_change ON alerts;
CREATE TRIGGER alerts_capture_change
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    WHEN (
        OLD.severity  IS DISTINCT FROM NEW.severity OR
        OLD.status    IS DISTINCT FROM NEW.status   OR
        OLD.raw_text  IS DISTINCT FROM NEW.raw_text
    )
    EXECUTE FUNCTION capture_alert_change();

-- ==========================================================
-- CDC via LISTEN / NOTIFY
-- ==========================================================
CREATE OR REPLACE FUNCTION notify_alert_needs_embedding() RETURNS trigger AS $$
BEGIN
    -- Only notify when the embedding is missing (newly inserted row, or
    -- a row whose embedding was invalidated by a raw_text change).
    IF NEW.embedding IS NULL THEN
        PERFORM pg_notify('alerts_changed', NEW.alert_id::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS alerts_notify_insert ON alerts;
CREATE TRIGGER alerts_notify_insert
    AFTER INSERT ON alerts
    FOR EACH ROW
    EXECUTE FUNCTION notify_alert_needs_embedding();

-- When raw_text changes, drop the embedding (NULL) so the post-update
-- NOTIFY fires and the worker re-embeds.
CREATE OR REPLACE FUNCTION invalidate_embedding_on_text_change() RETURNS trigger AS $$
BEGIN
    IF OLD.raw_text IS DISTINCT FROM NEW.raw_text THEN
        NEW.embedding := NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS alerts_invalidate_embedding ON alerts;
CREATE TRIGGER alerts_invalidate_embedding
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    EXECUTE FUNCTION invalidate_embedding_on_text_change();

DROP TRIGGER IF EXISTS alerts_notify_update ON alerts;
CREATE TRIGGER alerts_notify_update
    AFTER UPDATE ON alerts
    FOR EACH ROW
    EXECUTE FUNCTION notify_alert_needs_embedding();
