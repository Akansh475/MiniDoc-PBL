# ContainerOS

A lightweight, educational container-management system built for a college PBL (Project-Based Learning) submission. It demonstrates core **Operating Systems** and **DBMS** concepts by managing real OS processes as "containers" while an Oracle database tracks all metadata, state, and history.

> **Note on scope:** This is *not* a Docker replacement. There are no Linux namespaces or cgroups — a "container" here is a real process launched via `fork()`/`exec()` and tracked end-to-end. The project's purpose is to demonstrate process lifecycle management and relational database concepts (transactions, ACID, PL/SQL, concurrency control), not to reimplement containerization.

## What it does

- Create, start, stop, restart, and delete containers (OS processes)
- Track process state through a lifecycle: `CREATED → RUNNING → STOPPED / EXITED / FAILED`
- Persist all container/process metadata, resource info, and logs in Oracle
- Demonstrate transactional consistency between DB state and actual OS state (rollback on failure)
- Demonstrate concurrency control via Oracle row locking

## Concepts demonstrated

**Operating Systems**
- Process creation (`fork()`, `exec()`)
- Process synchronization (`wait()`/`waitpid()`)
- Signal handling (`SIGTERM`/`SIGKILL`) for stop/restart
- Process lifecycle and state management
- Basic resource limiting (`setrlimit()`)

**DBMS (Oracle)**
- ER modeling and normalized relational schema
- Transactions and ACID guarantees (commit/rollback on process launch failure)
- PL/SQL stored procedures and triggers
- Concurrency control via row-level locking (`SELECT ... FOR UPDATE`)

## Architecture
CLI (Python)
│
▼
Container Manager ──────────► Oracle DB (metadata, state, logs)
│
▼
Process Manager (C) ──► fork() / exec() / wait() / signals

## Project structure
containeros/
├── db/
│ ├── schema.sql # Table definitions
│ ├── procedures.sql # PL/SQL stored procedures
│ ├── triggers.sql # PL/SQL triggers
│ └── seed.sql # Sample data
├── runtime/ # C: process creation and lifecycle
│ ├── process_manager.c
│ └── process_manager.h
├── cli/ # Python CLI, talks to Oracle + runtime binary
│ └── containeros.py
├── docs/
│ ├── ER-diagram.png
│ └── report.md
└── README.md

## Tech stack

- **Runtime layer:** C (process management via Linux syscalls)
- **Backend/CLI:** Python
- **Database:** Oracle
- **OS:** Linux/Ubuntu (development target)

## Status

🚧 In development — built in phases (schema → CLI skeleton → process runner → integration → transactions → PL/SQL → concurrency demo).
