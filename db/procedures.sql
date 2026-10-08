-- ============================================================================
-- MiniDocker - Stored Procedures Package & Routines (Oracle PL/SQL)
-- ============================================================================
-- Academic Focus:
-- 1. Encapsulation of Business Logic in Database Tier
-- 2. Transaction Management (SAVEPOINT, COMMIT, ROLLBACK)
-- 3. Pessimistic Concurrency Control using SELECT ... FOR UPDATE
-- 4. Exception Handling with User-Defined Application Errors (RAISE_APPLICATION_ERROR)
-- 5. Out Parameters & Cursor Handling
-- ============================================================================

CREATE OR REPLACE PACKAGE minidocker_pkg AS
    -- Procedure to register and start a new container
    PROCEDURE create_container(
        p_name         IN  VARCHAR2,
        p_command      IN  VARCHAR2,
        p_cpu_limit    IN  NUMBER,
        p_memory_limit IN  NUMBER,
        p_pid          IN  NUMBER,
        p_container_id OUT NUMBER,
        p_status       OUT VARCHAR2
    );

    -- Procedure to stop an active container
    PROCEDURE stop_container(
        p_container_id IN  NUMBER,
        p_new_status   OUT VARCHAR2
    );

    -- Procedure to record container restart with new OS PID
    PROCEDURE restart_container(
        p_container_id IN  NUMBER,
        p_new_pid      IN  NUMBER,
        p_new_status   OUT VARCHAR2
    );

    -- Procedure to remove container and its cascading records
    PROCEDURE delete_container(
        p_container_id IN NUMBER
    );

    -- Procedure to synchronize real OS process state with DB state
    PROCEDURE sync_container_status(
        p_container_id IN NUMBER,
        p_real_status  IN VARCHAR2
    );

    -- Procedure to record time-series CPU and memory telemetry
    PROCEDURE record_usage(
        p_container_id IN NUMBER,
        p_cpu_usage    IN NUMBER,
        p_memory_usage IN NUMBER
    );

    -- Procedure to inspect container metadata and latest telemetry
    PROCEDURE get_container_details(
        p_container_id   IN  NUMBER,
        p_name           OUT VARCHAR2,
        p_command        OUT VARCHAR2,
        p_pid            OUT NUMBER,
        p_status         OUT VARCHAR2,
        p_cpu_limit      OUT NUMBER,
        p_memory_limit   OUT NUMBER,
        p_created_at     OUT TIMESTAMP,
        p_updated_at     OUT TIMESTAMP,
        p_latest_cpu     OUT NUMBER,
        p_latest_mem     OUT NUMBER
    );
END minidocker_pkg;
/

CREATE OR REPLACE PACKAGE BODY minidocker_pkg AS

    -- ========================================================================
    -- PROCEDURE: create_container
    -- Atomically inserts container record. If PID is supplied and positive,
    -- marks container RUNNING; otherwise CREATED.
    -- Demonstrates: SAVEPOINT and conditional transaction commit.
    -- ========================================================================
    PROCEDURE create_container(
        p_name         IN  VARCHAR2,
        p_command      IN  VARCHAR2,
        p_cpu_limit    IN  NUMBER,
        p_memory_limit IN  NUMBER,
        p_pid          IN  NUMBER,
        p_container_id OUT NUMBER,
        p_status       OUT VARCHAR2
    ) IS
        v_initial_status VARCHAR2(20);
    BEGIN
        -- Establish transactional savepoint before insertion
        SAVEPOINT sp_create_container;

        IF p_command IS NULL OR TRIM(p_command) IS NULL THEN
            RAISE_APPLICATION_ERROR(-20002, 'Command cannot be null or empty.');
        END IF;

        IF p_pid IS NOT NULL AND p_pid > 0 THEN
            v_initial_status := 'RUNNING';
        ELSE
            v_initial_status := 'CREATED';
        END IF;

        INSERT INTO containers (
            container_name,
            command,
            pid,
            status,
            cpu_limit,
            memory_limit,
            created_at,
            updated_at
        ) VALUES (
            p_name,
            p_command,
            p_pid,
            v_initial_status,
            NVL(p_cpu_limit, 0),
            NVL(p_memory_limit, 0),
            SYSTIMESTAMP,
            SYSTIMESTAMP
        ) RETURNING container_id, status INTO p_container_id, p_status;

        -- Commit changes upon successful persistence
        COMMIT;

    EXCEPTION
        WHEN DUP_VAL_ON_INDEX THEN
            ROLLBACK TO sp_create_container;
            RAISE_APPLICATION_ERROR(-20001, 'A container with name "' || p_name || '" already exists.');
        WHEN OTHERS THEN
            ROLLBACK TO sp_create_container;
            RAISE_APPLICATION_ERROR(-20099, 'Failed to create container: ' || SQLERRM);
    END create_container;

    -- ========================================================================
    -- PROCEDURE: stop_container
    -- Implements row-level exclusive lock (SELECT ... FOR UPDATE) to ensure
    -- no concurrent modification occurs while changing status to STOPPED.
    -- ========================================================================
    PROCEDURE stop_container(
        p_container_id IN  NUMBER,
        p_new_status   OUT VARCHAR2
    ) IS
        v_curr_status VARCHAR2(20);
        v_pid         NUMBER;
    BEGIN
        -- Row-level locking to prevent race conditions during state transition
        SELECT status, pid
          INTO v_curr_status, v_pid
          FROM containers
         WHERE container_id = p_container_id
           FOR UPDATE;

        IF v_curr_status = 'STOPPED' THEN
            p_new_status := 'STOPPED';
            COMMIT;
            RETURN;
        END IF;

        UPDATE containers
           SET status = 'STOPPED',
               updated_at = SYSTIMESTAMP
         WHERE container_id = p_container_id;

        p_new_status := 'STOPPED';
        COMMIT;

    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE_APPLICATION_ERROR(-20003, 'Container ID ' || p_container_id || ' not found.');
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE_APPLICATION_ERROR(-20099, 'Failed to stop container: ' || SQLERRM);
    END stop_container;

    -- ========================================================================
    -- PROCEDURE: restart_container
    -- Locks container, associates new operating system PID, transitions to RUNNING.
    -- ========================================================================
    PROCEDURE restart_container(
        p_container_id IN  NUMBER,
        p_new_pid      IN  NUMBER,
        p_new_status   OUT VARCHAR2
    ) IS
        v_curr_status VARCHAR2(20);
    BEGIN
        -- Lock row for update
        SELECT status
          INTO v_curr_status
          FROM containers
         WHERE container_id = p_container_id
           FOR UPDATE;

        UPDATE containers
           SET pid = p_new_pid,
               status = 'RUNNING',
               updated_at = SYSTIMESTAMP
         WHERE container_id = p_container_id;

        p_new_status := 'RUNNING';
        COMMIT;

    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE_APPLICATION_ERROR(-20003, 'Container ID ' || p_container_id || ' not found.');
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE_APPLICATION_ERROR(-20099, 'Failed to restart container: ' || SQLERRM);
    END restart_container;

    -- ========================================================================
    -- PROCEDURE: delete_container
    -- Locks and deletes container. Process logs & resource usage cascade delete.
    -- ========================================================================
    PROCEDURE delete_container(
        p_container_id IN NUMBER
    ) IS
        v_dummy NUMBER;
    BEGIN
        -- Verify existence and lock row
        SELECT container_id
          INTO v_dummy
          FROM containers
         WHERE container_id = p_container_id
           FOR UPDATE;

        DELETE FROM containers
         WHERE container_id = p_container_id;

        COMMIT;

    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE_APPLICATION_ERROR(-20003, 'Container ID ' || p_container_id || ' not found.');
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE_APPLICATION_ERROR(-20099, 'Failed to delete container: ' || SQLERRM);
    END delete_container;

    -- ========================================================================
    -- PROCEDURE: sync_container_status
    -- Synchronizes DB state when the runtime detects process termination or crash.
    -- Ensures DB NEVER reports RUNNING if OS process has died.
    -- ========================================================================
    PROCEDURE sync_container_status(
        p_container_id IN NUMBER,
        p_real_status  IN VARCHAR2
    ) IS
        v_curr_status VARCHAR2(20);
    BEGIN
        SELECT status
          INTO v_curr_status
          FROM containers
         WHERE container_id = p_container_id
           FOR UPDATE;

        IF v_curr_status != p_real_status THEN
            UPDATE containers
               SET status = p_real_status,
                   updated_at = SYSTIMESTAMP
             WHERE container_id = p_container_id;
        END IF;

        COMMIT;

    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            NULL; -- Silent ignore if already removed
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE_APPLICATION_ERROR(-20099, 'Failed to sync container status: ' || SQLERRM);
    END sync_container_status;

    -- ========================================================================
    -- PROCEDURE: record_usage
    -- Logs real-time CPU% and memory metrics into resource_usage time-series table.
    -- ========================================================================
    PROCEDURE record_usage(
        p_container_id IN NUMBER,
        p_cpu_usage    IN NUMBER,
        p_memory_usage IN NUMBER
    ) IS
    BEGIN
        INSERT INTO resource_usage (
            container_id,
            cpu_usage,
            memory_usage,
            recorded_at
        ) VALUES (
            p_container_id,
            p_cpu_usage,
            p_memory_usage,
            SYSTIMESTAMP
        );

        COMMIT;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE_APPLICATION_ERROR(-20099, 'Failed to record resource usage: ' || SQLERRM);
    END record_usage;

    -- ========================================================================
    -- PROCEDURE: get_container_details
    -- Returns comprehensive container state and latest recorded resource usage.
    -- ========================================================================
    PROCEDURE get_container_details(
        p_container_id   IN  NUMBER,
        p_name           OUT VARCHAR2,
        p_command        OUT VARCHAR2,
        p_pid            OUT NUMBER,
        p_status         OUT VARCHAR2,
        p_cpu_limit      OUT NUMBER,
        p_memory_limit   OUT NUMBER,
        p_created_at     OUT TIMESTAMP,
        p_updated_at     OUT TIMESTAMP,
        p_latest_cpu     OUT NUMBER,
        p_latest_mem     OUT NUMBER
    ) IS
    BEGIN
        SELECT container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at
          INTO p_name, p_command, p_pid, p_status, p_cpu_limit, p_memory_limit, p_created_at, p_updated_at
          FROM containers
         WHERE container_id = p_container_id;

        -- Fetch most recent metrics record if available
        BEGIN
            SELECT cpu_usage, memory_usage
              INTO p_latest_cpu, p_latest_mem
              FROM (
                  SELECT cpu_usage, memory_usage
                    FROM resource_usage
                   WHERE container_id = p_container_id
                   ORDER BY recorded_at DESC
              )
             WHERE ROWNUM = 1;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN
                p_latest_cpu := 0.00;
                p_latest_mem := 0.00;
        END;

    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE_APPLICATION_ERROR(-20003, 'Container ID ' || p_container_id || ' not found.');
    END get_container_details;

END minidocker_pkg;
/

COMMIT;
