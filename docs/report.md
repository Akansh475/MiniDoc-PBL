# MiniDocker (ContainerOS) - Project-Based Learning (PBL) Report

**Course Domain:** Operating Systems (OS) & Database Management Systems (DBMS)  
**Project Title:** MiniDocker (ContainerOS): Academic Container Lifecycle Management System  
**Target Environment:** Linux / POSIX (macOS compatible development)  
**Primary Technologies:** C (POSIX System Calls), Python (CLI & Orchestration), Oracle PL/SQL / Relational SQL  

---

## 1. Executive Summary & Abstract

**MiniDocker (ContainerOS)** is an educational, full-stack systems project created for an academic Project-Based Learning (PBL) curriculum. It demonstrates the intersection of low-level **Operating Systems** concepts and enterprise **Database Management Systems (DBMS)** principles.

Unlike modern production container engines (such as Docker or Podman) which rely on Linux kernel namespaces (`clone(CLONE_NEWPID, ...)`) and Control Groups (`cgroups`), MiniDocker treats native OS processes as containerized workloads. Each workload is instantiated via POSIX system calls (`fork()`, `execvp()`), governed by kernel resource constraints (`setrlimit()`), and controlled via asynchronous signal dispatch (`SIGTERM`, `SIGKILL`).

Simultaneously, MiniDocker couples the OS process lifecycle with an **Oracle Relational Database**. Every lifecycle transition (`CREATED`, `RUNNING`, `STOPPED`, `EXITED`, `FAILED`), resource telemetry metric (CPU percentage, Resident Set Size memory), and operational audit event is managed with strict ACID transaction guarantees. Database integrity is preserved through PL/SQL stored procedures (`minidocker_pkg`), automated triggers (`BEFORE/AFTER INSERT/UPDATE`), and pessimistic row-level locking (`SELECT ... FOR UPDATE`) to prevent race conditions during concurrent management operations.

---

## 2. Problem Statement & Academic Objectives

### 2.1 The Problem
In standard academic curricula, Operating Systems and Database Systems are taught as isolated disciplines:
- OS courses teach process lifecycles, scheduling, and system calls in isolation from persistence layers.
- DBMS courses explore relational modeling, normalization, and ACID transactions using synthetic banking or e-commerce datasets without interactions with kernel-level subsystems.

MiniDocker bridges this divide by answering:
1. *How can an application guarantee transactional consistency (ACID) between ephemeral OS process states and persistent database records?*
2. *What happens when a low-level system call (`fork()` or `exec()`) fails after a database record has been staged, and how does rollback prevent orphaned states?*
3. *How do database concurrency mechanisms (row locks, transaction isolation) resolve race conditions when multiple CLI clients manipulate shared OS processes?*

### 2.2 Key Learning Objectives
- **OS Concepts:** Process creation (`fork`, `execvp`), process synchronization (`waitpid`), signal handling (`SIGTERM`, `SIGKILL`), kernel resource quotas (`setrlimit`), and telemetry extraction.
- **DBMS Concepts:** 3NF relational modeling, foreign key cascades, domain check constraints, PL/SQL stored procedures with transaction boundaries (`COMMIT`/`ROLLBACK`), automated audit triggers, and row-level concurrency control (`FOR UPDATE`).

---

## 3. High-Level Architecture & Component Design

The system implements a decoupled, 3-tier modular architecture:

```
┌────────────────────────────────────────────────────────┐
│                   CLI Layer (Python)                   │
│             cli/containeros.py (Entrypoint)            │
│  [run | ps | inspect | stop | kill | restart | rm | logs] │
└───────────────┬────────────────────────┬───────────────┘
                │                        │
   Process      │                        │  ACID State Management &
   Control /    │                        │  Audit Logging
   Telemetry    │                        │
                ▼                        ▼
┌───────────────────────────┐  ┌─────────────────────────┐
│     OS Runtime Layer      │  │     Database Layer      │
│            (C)            │  │     (Oracle/SQL)        │
│ runtime/process_manager.c │  │ db/schema.sql           │
├───────────────────────────┤  │ db/procedures.sql       │
│ • fork() & execvp()       │  │ db/triggers.sql         │
│ • waitpid(WNOHANG)        │  │ db/seed.sql             │
│ • kill(SIGTERM/SIGKILL)   │  │ db/concurrency_demo.sql │
│ • setrlimit(CPU, MEM)     │  ├─────────────────────────┤
│ • /tmp/minidocker_logs/   │  │ • minidocker_pkg        │
└───────────────────────────┘  │ • Automated Triggers    │
                               │ • Row-level Locking     │
                               └─────────────────────────┘
```

### Component Breakdown
1. **User Interaction & Orchestration (`cli/containeros.py`):**
   - Implements a user-friendly command-line interface mimicking container tools (`run`, `ps`, `inspect`, `stop`, `kill`, `restart`, `rm`, `logs`).
   - Acts as the transaction coordinator, reconciling OS state with database state.
   - Includes automatic SQLite fallback for offline demonstrations and viva examinations.

2. **C Process Manager (`runtime/process_manager.c` & `runtime/process_manager.h`):**
   - Compiles to a standalone binary (`process_manager`) providing atomic CLI subcommands (`run`, `status`, `stop`, `kill`, `restart`, `metrics`).
   - Interacts directly with the POSIX kernel interface without third-party runtime dependencies.
   - Redirects stdout/stderr to `/tmp/minidocker_logs/proc_<PID>.log`.

3. **Relational Database Engine (`db/*.sql`):**
   - **Schema (`schema.sql`):** Normalized third normal form (3NF) tables with referential integrity and indexes.
   - **Stored Procedures (`procedures.sql`):** Encapsulated business logic within `minidocker_pkg` ensuring single-transaction state changes.
   - **Triggers (`triggers.sql`):** Non-bypassable audit logging in `process_logs`.
   - **Concurrency Testing (`concurrency_demo.sql`):** Reproducible scripts demonstrating lock contention and isolation.

---

## 4. Operating Systems Concepts Demonstrated

### 4.1 Process Creation via `fork()`, `execl()`, and Process Supervisor Pattern
Process spawning in `runtime/process_manager.c` implements a resilient supervisor pattern:
1. The parent process calls `fork()` to spawn an asynchronous **Supervisor Process**.
2. The Supervisor process executes `setsid()` to detach from the controlling terminal session.
3. The Supervisor forks the **Child Workload Process**:
   - The child sets its process group (`setpgid(0, 0)`).
   - Applies resource quotas via `setrlimit()`.
   - Redirects `stdin` to `/dev/null`, and `stdout`/`stderr` to `/tmp/minidocker_logs/proc_<PID>.log`.
   - Invokes `execl("/bin/sh", "sh", "-c", command, (char *)NULL)`.
4. The Supervisor reports the child's `workload_pid` back to the parent CLI caller via a synchronous pipe and then enters a blocking `waitpid(child_pid, &status, 0)` call.
5. When the child terminates or receives a terminating signal, the Supervisor captures the exact exit code (`WEXITSTATUS`) or signal (`WTERMSIG`) and records terminal metadata into `/tmp/minidocker_logs/proc_<PID>.meta`.
6. This architecture ensures that even when the short-lived CLI process exits, the child's exit status is never lost to PID 1 adoption.

### 4.2 Non-Blocking Process Synchronization and Exit Code Recovery
When querying status via `check_process_status(pid)`:
1. MiniDocker tests if the process is active in the OS process table using `kill(pid, 0)`. If alive, it returns `STATE_RUNNING`.
2. If `kill(pid, 0)` returns `ESRCH` (process terminated), MiniDocker parses the supervisor metadata file `/tmp/minidocker_logs/proc_<pid>.meta`:
   - `exit_code == 0` -> `STATE_EXITED`
   - `exit_code != 0` -> `STATE_FAILED` (exact exit code preserved)
   - Terminated by `SIGTERM` / `SIGKILL` -> `STATE_STOPPED`
   - Terminated by other signal (e.g. `SIGSEGV`, `SIGXCPU`) -> `STATE_FAILED`

### 4.3 Signal Dispatch & Lifecycle Management
- **Graceful Termination (`SIGTERM`) with Escalation:** Dispatched by `containeros stop <ID>`. Dispatches `SIGTERM` to the process group (`-pid`). The CLI polls the process for up to 2.5 seconds; if the process does not exit, it automatically escalates to `SIGKILL`.
- **Forceful Termination (`SIGKILL`):** Dispatched by `containeros kill <ID>`. Cannot be caught or ignored; forces immediate termination by the kernel scheduler.
- **PID Reuse Protection:** If a container is already in `STOPPED`, `EXITED`, or `FAILED` state, `stop` and `kill` commands refrain from sending signals to the host OS, preventing accidental termination of unrelated processes if the PID was recycled by the kernel.

### 4.4 Kernel Resource Limiting via `setrlimit()`
MiniDocker enforces quotas before invoking `execl`:
- `RLIMIT_CPU`: Maximum CPU consumption time in seconds. If exceeded, the kernel dispatches `SIGXCPU` and terminates the process.
- `RLIMIT_AS` (or `RLIMIT_DATA`): Address space and memory bounds in bytes.

```c
if (limits->cpu_limit_seconds > 0) {
    struct rlimit rl_cpu;
    rl_cpu.rlim_cur = limits->cpu_limit_seconds;
    rl_cpu.rlim_max = limits->cpu_limit_seconds;
    setrlimit(RLIMIT_CPU, &rl_cpu);
}
```

### 4.5 Container Lifecycle State Machine

```
       ┌──────────────┐
       │   CREATED    │
       └──────┬───────┘
              │ fork() / execvp() success
              ▼
       ┌──────────────┐
       │   RUNNING    │◄──────────────┐
       └──────┬───────┘               │
              │                       │ restart()
    ┌─────────┼──────────┐            │ (New PID)
    │         │          │            │
    │SIGTERM  │Process   │Crash /     │
    │SIGKILL  │exits 0   │non-zero /  │
    ▼         ▼          ▼            │
┌─────────┐ ┌─────────┐ ┌─────────┐   │
│ STOPPED │ │ EXITED  │ │ FAILED  │───┘
└─────────┘ └─────────┘ └─────────┘
```

---

## 5. DBMS Concepts & Relational Architecture

### 5.1 Normalized Relational Schema Design (3NF)

The database schema models container workloads, users, audit history, and telemetry metrics:

```mermaid
erDiagram
    USERS ||--o{ CONTAINERS : "launches"
    CONTAINERS ||--o{ PROCESS_LOGS : "records"
    CONTAINERS ||--o{ RESOURCE_USAGE : "telemetry"

    USERS {
        number user_id PK
        varchar2 username UK
        timestamp created_at
    }

    CONTAINERS {
        number container_id PK
        number user_id FK
        varchar2 container_name UK
        varchar2 command
        number pid
        varchar2 status
        number cpu_limit
        number memory_limit
        timestamp created_at
        timestamp updated_at
    }

    PROCESS_LOGS {
        number log_id PK
        number container_id FK
        varchar2 action
        varchar2 old_status
        varchar2 new_status
        timestamp timestamp
    }

    RESOURCE_USAGE {
        number usage_id PK
        number container_id FK
        number cpu_usage
        number memory_usage
        timestamp recorded_at
    }
```

### 5.2 Constraints & Referential Integrity
- **Primary Keys:** Auto-generated sequence/identity columns (`user_id`, `container_id`, `log_id`, `usage_id`).
- **Foreign Keys:**
  - `containers.user_id` references `users.user_id` with `ON DELETE CASCADE`.
  - `process_logs.container_id` and `resource_usage.container_id` reference `containers.container_id` with `ON DELETE CASCADE`. Removing a container automatically cleans up child telemetry and logs.
- **Unique Constraints:** `uq_users_username` and `uq_container_name` guarantee non-colliding identifiers.
- **Domain Check Constraint:** `chk_container_status CHECK (status IN ('CREATED', 'RUNNING', 'STOPPED', 'EXITED', 'FAILED'))`.

### 5.3 B-Tree Indexing Strategy
To support real-time querying without full-table scans:
1. `idx_containers_user_id`: Fast join and cascade verification between users and workloads.
2. `idx_process_logs_cid` & `idx_resource_usage_cid`: Indexed on foreign keys to eliminate table locks when deleting parent container records.
3. `idx_containers_status`: Accelerates filtering active workloads (`SELECT ... WHERE status = 'RUNNING'`).
4. `idx_containers_pid`: Enables fast PID-to-container reconciliation lookups.

### 5.4 ACID Guarantees in Container Management
- **Atomicity:** A container launch is an atomic unit. If the C process runtime fails to spawn the command, any database transaction is rolled back (`ROLLBACK`). Conversely, if the database transaction fails to commit (e.g. duplicate name constraint violation), the spawned OS process is caught and killed (`SIGKILL`) to prevent orphaned processes.
- **Consistency:** Database check constraints prevent containers from entering invalid states (e.g. `UNKNOWN` or `PAUSED` are rejected at the database engine level).
- **Isolation:** Updates to containers (`stop`, `restart`, `sync`) execute under pessimistic row-level locking (`SELECT ... FOR UPDATE` in Oracle / `BEGIN IMMEDIATE` in SQLite), preventing dirty writes or conflicting updates.
- **Durability:** Committed state transitions and process logs are persisted to disk and transaction logs.

### 5.5 PL/SQL Package: `minidocker_pkg`
Business logic is centralized in the database engine:
- `minidocker_pkg.create_container(...)`: Inserts metadata, initializes timestamp, and outputs generated ID.
- `minidocker_pkg.stop_container(...)`: Validates transition, updates state to `STOPPED`, and updates `updated_at`.
- `minidocker_pkg.restart_container(...)`: Updates process with new PID and transitions state to `RUNNING`.
- `minidocker_pkg.delete_container(...)`: Verifies process is stopped, and executes cascading delete.
- `minidocker_pkg.record_usage(...)`: Inserts time-series CPU/memory observations.
- `minidocker_pkg.sync_container_status(...)`: Reconciles kernel state with database status.

### 5.6 Automated Event Triggers (Dual-Engine Parity)
The database enforces non-bypassable audit logging at the storage tier across both Oracle and SQLite:
- `trg_containers_updated_at`: In Oracle, automatically synchronizes `:NEW.updated_at = SYSTIMESTAMP` on row update.
- `trg_container_created_log`: Fires `AFTER INSERT ON containers`, automatically recording `CONTAINER_CREATED` in `process_logs`.
- `trg_container_status_log`: Fires `AFTER UPDATE OF status ON containers`. Dynamically derives audit action (`CONTAINER_STARTED`, `CONTAINER_STOPPED`, `CONTAINER_RESTARTED`, `CONTAINER_COMPLETED`, or `CONTAINER_CRASHED_OR_FAILED`) and appends immutable records to `process_logs`.

### 5.7 Concurrency Control & Row-Level Locking
When two administrative sessions attempt to modify the same container simultaneously (e.g., Session 1 issues `stop` while Session 2 issues `restart`):
- Without locking: A classic **Lost Update** anomaly occurs, leaving the database state inconsistent with the actual OS process table.
- With locking (`SELECT status, pid FROM containers WHERE container_id = p_id FOR UPDATE`):
  Session 1 acquires an exclusive row lock. Session 2 waits (or times out) until Session 1 completes `COMMIT` or `ROLLBACK`.

---

## 6. Implementation Verification & Automated Test Evidence

### 6.1 Automated Test Suite (`tests/test_lifecycle.py`)
The project features a dedicated regression test suite executable via Python's standard `unittest`:
```bash
python3 -m unittest discover tests
```

### 6.2 Test Results Output Matrix
All tests execute end-to-end against real OS processes and relational storage:

| Test Identifier | Test Function | Verified OS & DBMS Behavior | Result |
| :--- | :--- | :--- | :--- |
| **TC-01** | `test_01_run_and_status` | Spawns background workload, assigns PID, inserts DB row, verifies triggers | **PASS** |
| **TC-02** | `test_02_duplicate_container_name_rollback` | Verifies UNIQUE constraint rollback and orphaned process cleanup | **PASS** |
| **TC-03** | `test_03_ps_listing` | Validates tabular output formatting and running vs all states | **PASS** |
| **TC-04** | `test_04_inspect_and_telemetry` | Validates metadata display and insertion into `resource_usage` table | **PASS** |
| **TC-05** | `test_05_stats_command` | Verifies real-time CPU% and memory RSS polling via `stats` command | **PASS** |
| **TC-06** | `test_06_graceful_stop_sigterm_and_kill` | Tests `SIGTERM`, escalation, and PID reuse guard on stopped container | **PASS** |
| **TC-07** | `test_07_failure_exit_code_detection` | Captures non-zero exit code (42) and marks state `FAILED` | **PASS** |
| **TC-08** | `test_08_removal_and_cascading_cleanup` | Validates `CASCADE` delete on child tables and removal of `/tmp` logs | **PASS** |
| **TC-09** | `test_09_invalid_inputs` | Verifies graceful error messages on nonexistent IDs and syntax errors | **PASS** |

Execution Evidence:
```text
Ran 9 tests in 4.255s
OK
```

---

## 7. Viva Voce / Defense Questions & Answers

### Q1: Why use an external C runtime instead of Python's `subprocess`?
> **Answer:** The primary objective of this project is demonstrating foundational Operating Systems concepts. High-level library abstractions hide `fork()`, `execl()`, `setrlimit()`, `waitpid()`, and signal dispatching behind high-level wrappers. Writing the runtime in C exposes the exact POSIX system calls, memory allocation boundaries, and kernel interaction.

### Q2: Why is a supervisor wrapper necessary instead of a direct `fork()` and `exec()`?
> **Answer:** In POSIX, a process can only be reaped using `waitpid()` by its **direct parent**. When a command-line utility spawns a background workload and exits, the workload is orphaned and adopted by `init` (PID 1). Any subsequent invocation of the CLI is an independent process and cannot reap the child (receiving `errno == ECHILD`), losing the exit code. MiniDocker uses a lightweight detached supervisor that stays attached to the child, executes a blocking `waitpid()`, and records the exact exit status and signal into `/tmp/minidocker_logs/proc_<PID>.meta`.

### Q3: How is ACID atomicity preserved if the database operation fails during container launch?
> **Answer:** The orchestrator employs a two-phase cleanup protocol:
> 1. Launch OS process via C runtime and obtain PID.
> 2. Attempt database insert within an explicit transaction (`BEGIN IMMEDIATE;` / PL/SQL `SAVEPOINT`).
> If step 2 raises an exception (e.g. duplicate container name violation), the exception handler catches the error, triggers `ProcessRuntime.stop(pid)` to terminate the newly spawned process, and rolls back the database transaction. No orphaned processes or ghost records remain.

### Q4: How does MiniDocker prevent PID reuse hazards?
> **Answer:** Operating systems recycle process IDs once a process terminates. If a container has already exited or stopped, issuing `kill(pid, SIGTERM)` might inadvertently signal an unrelated host application that was subsequently assigned that same PID. MiniDocker verifies the database state prior to signal dispatch: if the container is already `STOPPED`, `EXITED`, or `FAILED`, the signal dispatch is aborted.

### Q5: Why are foreign key columns indexed?
> **Answer:** In relational databases (including Oracle and SQLite), when a parent row is deleted, the database engine must verify or cascade deletes to referencing child tables (`process_logs`, `resource_usage`). If the foreign key column is not indexed, the database engine must execute a full table scan or place a share-row lock on the entire child table, degrading concurrent transaction throughput.

---

## 8. Conclusion

The **MiniDocker (ContainerOS)** Project-Based Learning submission successfully integrates practical Operating Systems programming with enterprise Database Management Systems techniques. By building a functional container manager that combines POSIX system calls with normalized, transaction-safe database storage, the project offers deep insight into process lifecycles, kernel resource control, ACID guarantees, PL/SQL stored procedures, automated triggers, and concurrency locking.
