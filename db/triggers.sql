-- ============================================================================
-- MiniDocker - Database Triggers (Oracle PL/SQL)
-- ============================================================================
-- Academic Focus:
-- 1. Automated Event-Driven Programming in DBMS
-- 2. Audit Trail Maintenance via AFTER UPDATE / AFTER INSERT Triggers
-- 3. Temporal Consistency via BEFORE UPDATE Triggers (:NEW.updated_at)
-- 4. Transparent State Transition Logging (Old vs New Status)
-- ============================================================================

-- ============================================================================
-- TRIGGER 1: trg_containers_updated_at
-- Automatically synchronizes updated_at timestamp prior to any UPDATE row event
-- ============================================================================
CREATE OR REPLACE TRIGGER trg_containers_updated_at
BEFORE UPDATE ON containers
FOR EACH ROW
BEGIN
    :NEW.updated_at := SYSTIMESTAMP;
END;
/

-- ============================================================================
-- TRIGGER 2: trg_container_created_log
-- Automatically captures the initial creation event of a container
-- Transition: NULL -> CREATED (or initial state)
-- ============================================================================
CREATE OR REPLACE TRIGGER trg_container_created_log
AFTER INSERT ON containers
FOR EACH ROW
BEGIN
    INSERT INTO process_logs (
        container_id,
        action,
        old_status,
        new_status,
        timestamp
    ) VALUES (
        :NEW.container_id,
        'CONTAINER_CREATED',
        NULL,
        :NEW.status,
        SYSTIMESTAMP
    );
END;
/

-- ============================================================================
-- TRIGGER 3: trg_container_status_log
-- Fires whenever status column changes.
-- Enforces lifecycle audit logging for all valid state transitions:
--   CREATED -> RUNNING
--   RUNNING -> STOPPED
--   RUNNING -> EXITED
--   RUNNING -> FAILED
--   STOPPED -> RUNNING
-- ============================================================================
CREATE OR REPLACE TRIGGER trg_container_status_log
AFTER UPDATE OF status ON containers
FOR EACH ROW
WHEN (OLD.status IS NULL OR OLD.status != NEW.status)
DECLARE
    v_action VARCHAR2(100);
BEGIN
    -- Derive human-readable audit action based on lifecycle transition
    IF :OLD.status = 'CREATED' AND :NEW.status = 'RUNNING' THEN
        v_action := 'CONTAINER_STARTED';
    ELSIF :OLD.status = 'RUNNING' AND :NEW.status = 'STOPPED' THEN
        v_action := 'CONTAINER_STOPPED';
    ELSIF :OLD.status = 'STOPPED' AND :NEW.status = 'RUNNING' THEN
        v_action := 'CONTAINER_RESTARTED';
    ELSIF :OLD.status = 'RUNNING' AND :NEW.status = 'EXITED' THEN
        v_action := 'CONTAINER_COMPLETED';
    ELSIF :NEW.status = 'FAILED' THEN
        v_action := 'CONTAINER_CRASHED_OR_FAILED';
    ELSE
        v_action := 'STATUS_CHANGED_TO_' || :NEW.status;
    END IF;

    INSERT INTO process_logs (
        container_id,
        action,
        old_status,
        new_status,
        timestamp
    ) VALUES (
        :NEW.container_id,
        v_action,
        :OLD.status,
        :NEW.status,
        SYSTIMESTAMP
    );
END;
/

COMMIT;
