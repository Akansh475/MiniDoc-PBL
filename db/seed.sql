-- ============================================================================
-- MiniDocker - Database Seed Data (Oracle SQL)
-- ============================================================================
-- Academic Focus:
-- 1. Populating realistic test datasets for demonstration and viva presentation
-- 2. Demonstrating relational integrity and foreign key relationships
-- 3. Pre-loading historical lifecycle states (CREATED, RUNNING, STOPPED, EXITED, FAILED)
-- 4. Sample telemetry time-series records for resource analysis
-- ============================================================================

-- Clean up any prior test seed data
DELETE FROM resource_usage;
DELETE FROM process_logs;
DELETE FROM containers;
DELETE FROM users;

-- ============================================================================
-- 1. SEED USERS
-- ============================================================================
INSERT INTO users (username, created_at)
VALUES ('admin', SYSTIMESTAMP - INTERVAL '7' DAY);

INSERT INTO users (username, created_at)
VALUES ('dev_akansh', SYSTIMESTAMP - INTERVAL '5' DAY);

INSERT INTO users (username, created_at)
VALUES ('dev_alex', SYSTIMESTAMP - INTERVAL '3' DAY);

INSERT INTO users (username, created_at)
VALUES ('qa_tester', SYSTIMESTAMP - INTERVAL '1' DAY);

-- ============================================================================
-- 2. SEED CONTAINERS
-- Demonstrating all 5 lifecycle states: CREATED, RUNNING, STOPPED, EXITED, FAILED
-- ============================================================================

-- Container 1: Web API service (RUNNING)
INSERT INTO containers (
    container_id, container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at
) VALUES (
    1,
    'web-api',
    'python3 -m http.server 8080',
    2401,
    'RUNNING',
    10,               -- 10 CPU seconds limit
    268435456,        -- 256 MB memory limit
    SYSTIMESTAMP - INTERVAL '2' HOUR,
    SYSTIMESTAMP - INTERVAL '2' HOUR
);

-- Container 2: Background worker (STOPPED)
INSERT INTO containers (
    container_id, container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at
) VALUES (
    2,
    'queue-worker',
    'python3 worker.py --concurrency=2',
    2408,
    'STOPPED',
    5,                -- 5 CPU seconds limit
    134217728,        -- 128 MB memory limit
    SYSTIMESTAMP - INTERVAL '6' HOUR,
    SYSTIMESTAMP - INTERVAL '1' HOUR
);

-- Container 3: Batch export job (EXITED successfully)
INSERT INTO containers (
    container_id, container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at
) VALUES (
    3,
    'batch-exporter',
    'python3 export_data.py --format=csv',
    2390,
    'EXITED',
    0,                -- Unlimited CPU
    0,                -- Unlimited Memory
    SYSTIMESTAMP - INTERVAL '1' DAY,
    SYSTIMESTAMP - INTERVAL '23' HOUR
);

-- Container 4: Faulty microservice (FAILED)
INSERT INTO containers (
    container_id, container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at
) VALUES (
    4,
    'faulty-service',
    '/usr/local/bin/non_existent_app',
    NULL,
    'FAILED',
    0,
    0,
    SYSTIMESTAMP - INTERVAL '4' HOUR,
    SYSTIMESTAMP - INTERVAL '4' HOUR
);

-- Container 5: Template staging container (CREATED)
INSERT INTO containers (
    container_id, container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at
) VALUES (
    5,
    'db-backup-staging',
    'sh run_backup.sh --full',
    NULL,
    'CREATED',
    15,
    536870912,        -- 512 MB
    SYSTIMESTAMP - INTERVAL '30' MINUTE,
    SYSTIMESTAMP - INTERVAL '30' MINUTE
);

-- ============================================================================
-- 3. SEED PROCESS LOGS (Lifecycle History)
-- ============================================================================

-- History for Container 1 (web-api: CREATED -> RUNNING)
INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (1, 'CONTAINER_CREATED', NULL, 'CREATED', SYSTIMESTAMP - INTERVAL '120' MINUTE);

INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (1, 'CONTAINER_STARTED', 'CREATED', 'RUNNING', SYSTIMESTAMP - INTERVAL '119' MINUTE);

-- History for Container 2 (queue-worker: CREATED -> RUNNING -> STOPPED)
INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (2, 'CONTAINER_CREATED', NULL, 'CREATED', SYSTIMESTAMP - INTERVAL '360' MINUTE);

INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (2, 'CONTAINER_STARTED', 'CREATED', 'RUNNING', SYSTIMESTAMP - INTERVAL '359' MINUTE);

INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (2, 'CONTAINER_STOPPED', 'RUNNING', 'STOPPED', SYSTIMESTAMP - INTERVAL '60' MINUTE);

-- History for Container 3 (batch-exporter: CREATED -> RUNNING -> EXITED)
INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (3, 'CONTAINER_CREATED', NULL, 'CREATED', SYSTIMESTAMP - INTERVAL '24' HOUR);

INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (3, 'CONTAINER_STARTED', 'CREATED', 'RUNNING', SYSTIMESTAMP - INTERVAL '1439' MINUTE);

INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (3, 'CONTAINER_COMPLETED', 'RUNNING', 'EXITED', SYSTIMESTAMP - INTERVAL '1380' MINUTE);

-- History for Container 4 (faulty-service: CREATED -> FAILED)
INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (4, 'CONTAINER_CREATED', NULL, 'CREATED', SYSTIMESTAMP - INTERVAL '240' MINUTE);

INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (4, 'CONTAINER_CRASHED_OR_FAILED', 'CREATED', 'FAILED', SYSTIMESTAMP - INTERVAL '239' MINUTE);

-- History for Container 5 (db-backup-staging: CREATED)
INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
VALUES (5, 'CONTAINER_CREATED', NULL, 'CREATED', SYSTIMESTAMP - INTERVAL '30' MINUTE);

-- ============================================================================
-- 4. SEED RESOURCE USAGE (Telemetry History)
-- ============================================================================

-- Telemetry for Container 1 (web-api)
INSERT INTO resource_usage (container_id, cpu_usage, memory_usage, recorded_at)
VALUES (1, 2.45, 45.20, SYSTIMESTAMP - INTERVAL '60' MINUTE);

INSERT INTO resource_usage (container_id, cpu_usage, memory_usage, recorded_at)
VALUES (1, 4.10, 48.75, SYSTIMESTAMP - INTERVAL '30' MINUTE);

INSERT INTO resource_usage (container_id, cpu_usage, memory_usage, recorded_at)
VALUES (1, 3.80, 50.10, SYSTIMESTAMP - INTERVAL '5' MINUTE);

-- Telemetry for Container 2 (queue-worker prior to stop)
INSERT INTO resource_usage (container_id, cpu_usage, memory_usage, recorded_at)
VALUES (2, 12.30, 84.60, SYSTIMESTAMP - INTERVAL '120' MINUTE);

INSERT INTO resource_usage (container_id, cpu_usage, memory_usage, recorded_at)
VALUES (2, 15.80, 92.10, SYSTIMESTAMP - INTERVAL '90' MINUTE);

COMMIT;
