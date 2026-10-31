#!/usr/bin/env python3
"""
MiniDocker CLI - containeros
============================
A simplified Docker-inspired container management CLI built for learning
Operating Systems and Database Management Systems (DBMS).

Integrates:
- Runtime Layer: C binary (process_manager) executing fork(), exec(), waitpid(), signals
- Database Layer: Oracle Database (PL/SQL stored procedures, triggers, ACID transactions)
  with an automatic embedded offline engine for instant portability and viva demo.

Supported Commands:
  containeros run "<command>" [--name <name>] [--cpu <sec>] [--memory <bytes>]
  containeros ps [--all]
  containeros inspect <container_id>
  containeros stop <container_id>
  containeros kill <container_id>
  containeros restart <container_id>
  containeros rm <container_id>
  containeros logs <container_id> [--output]
"""

import sys
import os
import json
import argparse
import subprocess
import sqlite3
import datetime
import time
from typing import Optional, Dict, Any, List

# Paths
CLI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CLI_DIR, ".."))
RUNTIME_BIN = os.path.join(PROJECT_ROOT, "runtime", "process_manager")
DEFAULT_SQLITE_DB = os.path.join(PROJECT_ROOT, "db", "minidocker_local.db")
LOG_DIR = "/tmp/minidocker_logs"

# Ensure runtime binary exists or compile on the fly
def ensure_runtime_binary():
    if not os.path.isfile(RUNTIME_BIN):
        c_src = os.path.join(PROJECT_ROOT, "runtime", "process_manager.c")
        if os.path.isfile(c_src):
            print("[INFO] Compiling C runtime binary (process_manager)...", file=sys.stderr)
            compile_cmd = ["gcc", "-Wall", "-O2", c_src, "-o", RUNTIME_BIN]
            res = subprocess.run(compile_cmd)
            if res.returncode != 0:
                print("[ERROR] Failed to compile C runtime binary", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"[ERROR] Runtime source not found at {c_src}", file=sys.stderr)
            sys.exit(1)


# ============================================================================
# C RUNTIME INTERFACE (OS SYSCALLS WRAPPER)
# ============================================================================
class ProcessRuntime:
    """Invokes the compiled C process manager binary and parses JSON results."""

    @staticmethod
    def run(command: str, cpu_limit: int = 0, memory_limit: int = 0) -> Dict[str, Any]:
        ensure_runtime_binary()
        cmd = [RUNTIME_BIN, "run", str(cpu_limit), str(memory_limit), command]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(res.stdout.strip())
        except Exception:
            return {
                "pid": -1,
                "status": "FAILED",
                "error": res.stderr.strip() or res.stdout.strip() or "Failed to parse runtime output"
            }

    @staticmethod
    def status(pid: int) -> Dict[str, Any]:
        ensure_runtime_binary()
        cmd = [RUNTIME_BIN, "status", str(pid)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(res.stdout.strip())
        except Exception:
            return {"pid": pid, "status": "UNKNOWN", "is_alive": False, "exit_code": -1}

    @staticmethod
    def stop(pid: int) -> Dict[str, Any]:
        ensure_runtime_binary()
        cmd = [RUNTIME_BIN, "stop", str(pid)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(res.stdout.strip())
        except Exception:
            return {"pid": pid, "status": "FAILED", "success": False, "error": res.stderr.strip()}

    @staticmethod
    def kill(pid: int) -> Dict[str, Any]:
        ensure_runtime_binary()
        cmd = [RUNTIME_BIN, "kill", str(pid)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(res.stdout.strip())
        except Exception:
            return {"pid": pid, "status": "FAILED", "success": False, "error": res.stderr.strip()}

    @staticmethod
    def restart(old_pid: int, command: str, cpu_limit: int = 0, memory_limit: int = 0) -> Dict[str, Any]:
        ensure_runtime_binary()
        cmd = [RUNTIME_BIN, "restart", str(old_pid), str(cpu_limit), str(memory_limit), command]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(res.stdout.strip())
        except Exception:
            return {"pid": -1, "status": "FAILED", "success": False, "error": res.stderr.strip()}

    @staticmethod
    def metrics(pid: int) -> Dict[str, Any]:
        ensure_runtime_binary()
        cmd = [RUNTIME_BIN, "metrics", str(pid)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(res.stdout.strip())
        except Exception:
            return {"pid": pid, "cpu_usage_pct": 0.0, "memory_usage_mb": 0.0, "is_alive": False}


# ============================================================================
# DATABASE ADAPTER (ORACLE WITH SQLITE FALLBACK)
# ============================================================================
class DatabaseManager:
    """
    Provides ACID transaction management and schema operations.
    Connects to Oracle if ORACLE_USER & ORACLE_DSN environment variables
    are provided; otherwise maintains an exact relational SQLite instance.
    """
    def __init__(self):
        self.oracle_conn = None
        self.sqlite_conn = None
        self.mode = "SQLITE"

        oracle_user = os.getenv("ORACLE_USER")
        oracle_pwd = os.getenv("ORACLE_PASSWORD", "")
        oracle_dsn = os.getenv("ORACLE_DSN")

        if oracle_user and oracle_dsn:
            try:
                import oracledb
                self.oracle_conn = oracledb.connect(
                    user=oracle_user,
                    password=oracle_pwd,
                    dsn=oracle_dsn
                )
                self.mode = "ORACLE"
            except Exception as e:
                print(f"[WARN] Failed to connect to Oracle DB ({e}). Falling back to local offline DB.", file=sys.stderr)
                self._init_sqlite()
        else:
            self._init_sqlite()

    def _init_sqlite(self):
        self.mode = "SQLITE"
        os.makedirs(os.path.dirname(DEFAULT_SQLITE_DB), exist_ok=True)
        self.sqlite_conn = sqlite3.connect(DEFAULT_SQLITE_DB, timeout=30.0)
        self.sqlite_conn.row_factory = sqlite3.Row
        self.sqlite_conn.execute("PRAGMA foreign_keys = ON;")
        self._migrate_sqlite_schema()
        self._create_sqlite_schema()

    def _migrate_sqlite_schema(self):
        """Ensures schema upgrades (e.g. user_id foreign key) apply to existing databases."""
        cur = self.sqlite_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='containers';")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(containers);")
            columns = [row[1] for row in cur.fetchall()]
            if "user_id" not in columns:
                try:
                    cur.execute("ALTER TABLE containers ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(user_id) ON DELETE CASCADE;")
                    self.sqlite_conn.commit()
                except Exception:
                    pass

    def _create_sqlite_schema(self):
        cur = self.sqlite_conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS containers (
                container_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(user_id) ON DELETE CASCADE,
                container_name TEXT UNIQUE NOT NULL,
                command TEXT NOT NULL,
                pid INTEGER,
                status TEXT NOT NULL CHECK(status IN ('CREATED', 'RUNNING', 'STOPPED', 'EXITED', 'FAILED')),
                cpu_limit INTEGER DEFAULT 0,
                memory_limit INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS process_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_id INTEGER NOT NULL REFERENCES containers(container_id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS resource_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_id INTEGER NOT NULL REFERENCES containers(container_id) ON DELETE CASCADE,
                cpu_usage REAL DEFAULT 0.0,
                memory_usage REAL DEFAULT 0.0,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_containers_user_id ON containers(user_id);
            CREATE INDEX IF NOT EXISTS idx_containers_status ON containers(status);
            CREATE INDEX IF NOT EXISTS idx_containers_pid ON containers(pid);
            CREATE INDEX IF NOT EXISTS idx_process_logs_cid ON process_logs(container_id);
            CREATE INDEX IF NOT EXISTS idx_resource_usage_cid ON resource_usage(container_id);

            -- Default Admin User
            INSERT OR IGNORE INTO users (user_id, username) VALUES (1, 'admin');

            -- Automated Audit Triggers (Parity with Oracle triggers.sql)
            CREATE TRIGGER IF NOT EXISTS trg_container_created_log
            AFTER INSERT ON containers
            FOR EACH ROW
            BEGIN
                INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
                VALUES (NEW.container_id, 'CONTAINER_CREATED', NULL, NEW.status, datetime('now'));
            END;

            CREATE TRIGGER IF NOT EXISTS trg_container_created_running_log
            AFTER INSERT ON containers
            FOR EACH ROW
            WHEN NEW.status = 'RUNNING'
            BEGIN
                INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
                VALUES (NEW.container_id, 'CONTAINER_STARTED', 'CREATED', 'RUNNING', datetime('now'));
            END;

            CREATE TRIGGER IF NOT EXISTS trg_container_status_log
            AFTER UPDATE OF status ON containers
            FOR EACH ROW
            WHEN OLD.status != NEW.status
            BEGIN
                INSERT INTO process_logs (container_id, action, old_status, new_status, timestamp)
                VALUES (
                    NEW.container_id,
                    CASE
                        WHEN OLD.status = 'CREATED' AND NEW.status = 'RUNNING' THEN 'CONTAINER_STARTED'
                        WHEN OLD.status = 'RUNNING' AND NEW.status = 'STOPPED' THEN 'CONTAINER_STOPPED'
                        WHEN OLD.status = 'STOPPED' AND NEW.status = 'RUNNING' THEN 'CONTAINER_RESTARTED'
                        WHEN OLD.status = 'RUNNING' AND NEW.status = 'EXITED' THEN 'CONTAINER_COMPLETED'
                        WHEN NEW.status = 'FAILED' THEN 'CONTAINER_CRASHED_OR_FAILED'
                        ELSE 'STATUS_CHANGED_TO_' || NEW.status
                    END,
                    OLD.status,
                    NEW.status,
                    datetime('now')
                );
            END;
        """)
        self.sqlite_conn.commit()

    # ------------------------------------------------------------------------
    # CONTAINER CRUD & STORED PROCEDURES IMPLEMENTATION
    # ------------------------------------------------------------------------

    def create_container(self, name: str, command: str, pid: int, cpu_limit: int, mem_limit: int, user_id: int = 1) -> int:
        """Atomically inserts container and logs CREATED / RUNNING state."""
        status = "RUNNING" if (pid and pid > 0) else "CREATED"

        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            p_id = cur.var(int)
            p_st = cur.var(str)
            cur.callproc("minidocker_pkg.create_container", [name, command, cpu_limit, mem_limit, pid, user_id, p_id, p_st])
            self.oracle_conn.commit()
            return p_id.getvalue()
        else:
            cur = self.sqlite_conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE;")
                cur.execute("""
                    INSERT INTO containers (user_id, container_name, command, pid, status, cpu_limit, memory_limit, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """, (user_id, name, command, pid, status, cpu_limit, mem_limit))
                cid = cur.lastrowid
                self.sqlite_conn.commit()
                return cid
            except Exception as e:
                self.sqlite_conn.rollback()
                raise e

    def get_container(self, container_id: int) -> Optional[Dict[str, Any]]:
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.execute("""
                SELECT container_id, container_name, command, pid, status, cpu_limit, memory_limit,
                       TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at,
                       TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI:SS') as updated_at
                FROM containers WHERE container_id = :1
            """, [container_id])
            row = cur.fetchone()
            if not row:
                return None
            cols = [col[0].lower() for col in cur.description]
            return dict(zip(cols, row))
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("SELECT * FROM containers WHERE container_id = ?", (container_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_containers(self, all_states: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM containers"
        if not all_states:
            query += " WHERE status = 'RUNNING'"
        query += " ORDER BY container_id ASC"

        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.execute(query)
            cols = [col[0].lower() for col in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]

    def stop_container(self, container_id: int) -> str:
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            p_new_st = cur.var(str)
            cur.callproc("minidocker_pkg.stop_container", [container_id, p_new_st])
            self.oracle_conn.commit()
            return p_new_st.getvalue()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            cur.execute("SELECT status FROM containers WHERE container_id = ?", (container_id,))
            row = cur.fetchone()
            if not row:
                self.sqlite_conn.rollback()
                raise ValueError(f"Container ID {container_id} not found")

            old_st = row["status"]
            if old_st != "STOPPED":
                cur.execute("""
                    UPDATE containers
                    SET status = 'STOPPED', updated_at = datetime('now')
                    WHERE container_id = ?
                """, (container_id,))
            self.sqlite_conn.commit()
            return "STOPPED"

    def restart_container(self, container_id: int, new_pid: int) -> str:
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            p_new_st = cur.var(str)
            cur.callproc("minidocker_pkg.restart_container", [container_id, new_pid, p_new_st])
            self.oracle_conn.commit()
            return p_new_st.getvalue()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            cur.execute("SELECT status FROM containers WHERE container_id = ?", (container_id,))
            row = cur.fetchone()
            if not row:
                self.sqlite_conn.rollback()
                raise ValueError(f"Container ID {container_id} not found")

            cur.execute("""
                UPDATE containers
                SET pid = ?, status = 'RUNNING', updated_at = datetime('now')
                WHERE container_id = ?
            """, (new_pid, container_id))
            self.sqlite_conn.commit()
            return "RUNNING"

    def delete_container(self, container_id: int):
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.callproc("minidocker_pkg.delete_container", [container_id])
            self.oracle_conn.commit()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            cur.execute("SELECT container_id FROM containers WHERE container_id = ?", (container_id,))
            if not cur.fetchone():
                self.sqlite_conn.rollback()
                raise ValueError(f"Container ID {container_id} not found")

            cur.execute("DELETE FROM containers WHERE container_id = ?", (container_id,))
            self.sqlite_conn.commit()

    def sync_status(self, container_id: int, real_status: str):
        """Reconciles database status with real operating system state."""
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.callproc("minidocker_pkg.sync_container_status", [container_id, real_status])
            self.oracle_conn.commit()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("BEGIN IMMEDIATE;")
            cur.execute("SELECT status FROM containers WHERE container_id = ?", (container_id,))
            row = cur.fetchone()
            if row and row["status"] != real_status:
                cur.execute("""
                    UPDATE containers
                    SET status = ?, updated_at = datetime('now')
                    WHERE container_id = ?
                """, (real_status, container_id))
            self.sqlite_conn.commit()

    def record_usage(self, container_id: int, cpu_usage: float, mem_usage: float):
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.callproc("minidocker_pkg.record_usage", [container_id, cpu_usage, mem_usage])
            self.oracle_conn.commit()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("""
                INSERT INTO resource_usage (container_id, cpu_usage, memory_usage, recorded_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (container_id, cpu_usage, mem_usage))
            self.sqlite_conn.commit()

    def get_resource_history(self, container_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        query = """
            SELECT usage_id, container_id, cpu_usage, memory_usage, recorded_at
            FROM resource_usage
            WHERE container_id = ?
            ORDER BY usage_id DESC
            LIMIT ?
        """
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.execute("""
                SELECT usage_id, container_id, cpu_usage, memory_usage, TO_CHAR(recorded_at, 'YYYY-MM-DD HH24:MI:SS') as recorded_at
                FROM (
                    SELECT * FROM resource_usage WHERE container_id = :1 ORDER BY usage_id DESC
                ) WHERE ROWNUM <= :2
            """, [container_id, limit])
            cols = [col[0].lower() for col in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute(query, (container_id, limit))
            return [dict(row) for row in cur.fetchall()]

    def get_logs(self, container_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT log_id, container_id, action, old_status, new_status, timestamp
            FROM process_logs
            WHERE container_id = ?
            ORDER BY log_id ASC
        """
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.execute(query.replace("?", ":1"), [container_id])
            cols = [col[0].lower() for col in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute(query, (container_id,))
            return [dict(row) for row in cur.fetchall()]

    def get_latest_metrics(self, container_id: int) -> Dict[str, float]:
        query = """
            SELECT cpu_usage, memory_usage
            FROM resource_usage
            WHERE container_id = ?
            ORDER BY usage_id DESC
            LIMIT 1
        """
        if self.mode == "ORACLE":
            cur = self.oracle_conn.cursor()
            cur.execute("""
                SELECT cpu_usage, memory_usage FROM (
                    SELECT cpu_usage, memory_usage FROM resource_usage
                    WHERE container_id = :1 ORDER BY usage_id DESC
                ) WHERE ROWNUM = 1
            """, [container_id])
            row = cur.fetchone()
            if row:
                return {"cpu_usage": float(row[0]), "memory_usage": float(row[1])}
            return {"cpu_usage": 0.0, "memory_usage": 0.0}
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute(query, (container_id,))
            row = cur.fetchone()
            if row:
                return {"cpu_usage": float(row["cpu_usage"]), "memory_usage": float(row["memory_usage"])}
            return {"cpu_usage": 0.0, "memory_usage": 0.0}


# ============================================================================
# CLI COMMAND IMPLEMENTATIONS
# ============================================================================

def cmd_run(args, db: DatabaseManager):
    command = args.command
    name = args.name or f"cntr-{int(time.time()) % 100000}"
    cpu_limit = args.cpu or 0
    mem_limit = args.memory or 0

    print(f"[*] Starting container workload '{name}'...")
    print(f"[*] Command: {command}")
    if cpu_limit:
        print(f"[*] CPU Limit: {cpu_limit}s")
    if mem_limit:
        print(f"[*] Memory Limit: {mem_limit} bytes")

    # Step 1: Launch OS process via C runtime
    res = ProcessRuntime.run(command, cpu_limit, mem_limit)

    # Step 2: Validate transactional consistency
    if res.get("status") != "RUNNING" or res.get("pid", -1) <= 0:
        error_msg = res.get("error", "Process runtime failed to spawn command")
        print(f"[ERROR] Process launch failed: {error_msg}", file=sys.stderr)
        print("[TRANSACTION] Rolling back. No database record created (Rule 2).", file=sys.stderr)
        sys.exit(1)

    pid = res["pid"]

    # Step 3: Commit record to database
    try:
        cid = db.create_container(name, command, pid, cpu_limit, mem_limit)
        print(f"[+] Container created and running successfully!")
        print(f"    Container ID : {cid}")
        print(f"    Name         : {name}")
        print(f"    PID          : {pid}")
        print(f"    Status       : RUNNING")
    except Exception as e:
        print(f"[ERROR] Database persistence failed: {e}", file=sys.stderr)
        print(f"[*] Cleaning up orphaned OS process {pid}...", file=sys.stderr)
        ProcessRuntime.stop(pid)
        sys.exit(1)


def cmd_ps(args, db: DatabaseManager):
    containers = db.list_containers(all_states=args.all)

    # Reconcile database status with actual OS status (Rule 1 & Rule 4)
    for c in containers:
        pid = c.get("pid")
        if c.get("status") == "RUNNING" and pid:
            rt_status = ProcessRuntime.status(pid)
            if not rt_status.get("is_alive", False):
                real_state = rt_status.get("status", "EXITED")
                db.sync_status(c["container_id"], real_state)
                c["status"] = real_state

    # Re-fetch after synchronization if not --all
    if not args.all:
        containers = [c for c in containers if c["status"] == "RUNNING"]

    if not containers:
        print("No containers found.")
        return

    # Display clean tabular layout
    print(f"{'ID':<6} {'NAME':<18} {'PID':<8} {'STATUS':<10} {'COMMAND'}")
    print("-" * 65)
    for c in containers:
        pid_str = str(c["pid"]) if c.get("pid") else "-"
        cmd_str = (c["command"][:25] + "..") if len(c["command"]) > 25 else c["command"]
        print(f"{c['container_id']:<6} {c['container_name']:<18} {pid_str:<8} {c['status']:<10} {cmd_str}")


def cmd_inspect(args, db: DatabaseManager):
    cid = args.container_id
    c = db.get_container(cid)
    if not c:
        print(f"[ERROR] Container ID {cid} not found", file=sys.stderr)
        sys.exit(1)

    pid = c.get("pid")
    cpu_pct = 0.0
    mem_mb = 0.0
    is_alive = False

    if pid and pid > 0:
        # Fetch real-time telemetry from runtime
        metrics = ProcessRuntime.metrics(pid)
        is_alive = metrics.get("is_alive", False)
        cpu_pct = metrics.get("cpu_usage_pct", 0.0)
        mem_mb = metrics.get("memory_usage_mb", 0.0)

        # Sync database if process unexpectedly died
        if not is_alive and c["status"] == "RUNNING":
            db.sync_status(cid, "EXITED")
            c["status"] = "EXITED"
        elif is_alive:
            # Record telemetry in database time-series table
            db.record_usage(cid, cpu_pct, mem_mb)

    print("==================================================")
    print(f"Container Inspection: ID {c['container_id']}")
    print("==================================================")
    print(f"  Container ID   : {c['container_id']}")
    print(f"  Name           : {c['container_name']}")
    print(f"  PID            : {c['pid'] if c['pid'] else '-'}")
    print(f"  Status         : {c['status']}")
    print(f"  Command        : {c['command']}")
    print(f"  CPU Limit      : {c['cpu_limit']} sec")
    print(f"  Memory Limit   : {c['memory_limit']} bytes")
    print(f"  Created At     : {c['created_at']}")
    print(f"  Last Updated   : {c['updated_at']}")
    print("--------------------------------------------------")
    print("Telemetry & Resource Usage:")
    print(f"  Process Alive  : {'YES' if is_alive else 'NO'}")
    print(f"  CPU Usage      : {cpu_pct:.2f}%")
    print(f"  Memory (RSS)   : {mem_mb:.2f} MB")
    log_file = f"{LOG_DIR}/proc_{pid}.log"
    print(f"  Runtime Log    : {log_file if os.path.exists(log_file) else 'N/A'}")
    print("==================================================")


def cmd_stop(args, db: DatabaseManager):
    cid = args.container_id
    c = db.get_container(cid)
    if not c:
        print(f"[ERROR] Container ID {cid} not found", file=sys.stderr)
        sys.exit(1)

    pid = c.get("pid")
    if c["status"] == "STOPPED":
        print(f"[*] Container {cid} is already STOPPED.")
        return

    print(f"[*] Stopping container {cid} (PID: {pid}) with SIGTERM...")
    if pid and pid > 0:
        ProcessRuntime.stop(pid)

    db.stop_container(cid)
    print(f"[+] Container {cid} stopped successfully.")


def cmd_kill(args, db: DatabaseManager):
    cid = args.container_id
    c = db.get_container(cid)
    if not c:
        print(f"[ERROR] Container ID {cid} not found", file=sys.stderr)
        sys.exit(1)

    pid = c.get("pid")
    print(f"[*] Force killing container {cid} (PID: {pid}) with SIGKILL...")
    if pid and pid > 0:
        ProcessRuntime.kill(pid)

    db.stop_container(cid)
    print(f"[+] Container {cid} force killed.")


def cmd_restart(args, db: DatabaseManager):
    cid = args.container_id
    c = db.get_container(cid)
    if not c:
        print(f"[ERROR] Container ID {cid} not found", file=sys.stderr)
        sys.exit(1)

    old_pid = c.get("pid") or 0
    command = c["command"]
    cpu_limit = c.get("cpu_limit", 0)
    mem_limit = c.get("memory_limit", 0)

    print(f"[*] Restarting container {cid}...")
    res = ProcessRuntime.restart(old_pid, command, cpu_limit, mem_limit)

    if not res.get("success", False) or res.get("pid", -1) <= 0:
        print(f"[ERROR] Failed to restart container: {res.get('error')}", file=sys.stderr)
        sys.exit(1)

    new_pid = res["pid"]
    db.restart_container(cid, new_pid)
    print(f"[+] Container {cid} restarted successfully. New PID: {new_pid}")


def cmd_rm(args, db: DatabaseManager):
    cid = args.container_id
    c = db.get_container(cid)
    if not c:
        print(f"[ERROR] Container ID {cid} not found", file=sys.stderr)
        sys.exit(1)

    if c["status"] == "RUNNING":
        print(f"[*] Container {cid} is RUNNING. Stopping before removal...")
        pid = c.get("pid")
        if pid:
            ProcessRuntime.stop(pid)

    db.delete_container(cid)
    print(f"[+] Container {cid} deleted from database.")


def cmd_logs(args, db: DatabaseManager):
    cid = args.container_id
    c = db.get_container(cid)
    if not c:
        print(f"[ERROR] Container ID {cid} not found", file=sys.stderr)
        sys.exit(1)

    print(f"==================================================")
    print(f"Audit & Lifecycle Logs: Container {cid} ({c['container_name']})")
    print(f"==================================================")
    logs = db.get_logs(cid)
    if not logs:
        print("No lifecycle events recorded.")
    else:
        print(f"{'TIMESTAMP':<20} {'ACTION':<26} {'TRANSITION'}")
        print("-" * 65)
        for log in logs:
            old_s = log['old_status'] or 'NULL'
            new_s = log['new_status']
            transition = f"{old_s} -> {new_s}"
            print(f"{str(log['timestamp']):<20} {log['action']:<26} {transition}")

    if args.output:
        pid = c.get("pid")
        log_file = f"{LOG_DIR}/proc_{pid}.log"
        print("\n---------------- Process Output ------------------")
        if pid and os.path.exists(log_file):
            with open(log_file, "r") as f:
                content = f.read()
                print(content if content else "(Process log file is empty)")
        else:
            print(f"No output log found at {log_file}")
    print("==================================================")


# ============================================================================
# CLI ENTRYPOINT
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        prog="containeros",
        description="MiniDocker - Academic Container Management System (OS + DBMS)"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # run
    p_run = subparsers.add_parser("run", help="Run a command as a tracked container workload")
    p_run.add_argument("command", help="Shell command to execute")
    p_run.add_argument("--name", help="Friendly name for the container")
    p_run.add_argument("--cpu", type=int, default=0, help="CPU time limit in seconds")
    p_run.add_argument("--memory", type=int, default=0, help="Memory limit in bytes")

    # ps
    p_ps = subparsers.add_parser("ps", help="List running or all containers")
    p_ps.add_argument("-a", "--all", action="store_true", help="List all containers including stopped")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Display detailed container metadata and resource telemetry")
    p_inspect.add_argument("container_id", type=int, help="Target container ID")

    # stop
    p_stop = subparsers.add_parser("stop", help="Gracefully stop a container with SIGTERM")
    p_stop.add_argument("container_id", type=int, help="Target container ID")

    # kill
    p_kill = subparsers.add_parser("kill", help="Forcefully kill a container with SIGKILL")
    p_kill.add_argument("container_id", type=int, help="Target container ID")

    # restart
    p_restart = subparsers.add_parser("restart", help="Restart a container with a fresh OS PID")
    p_restart.add_argument("container_id", type=int, help="Target container ID")

    # rm
    p_rm = subparsers.add_parser("rm", help="Remove container and delete database records")
    p_rm.add_argument("container_id", type=int, help="Target container ID")

    # logs
    p_logs = subparsers.add_parser("logs", help="View lifecycle transition audit trail")
    p_logs.add_argument("container_id", type=int, help="Target container ID")
    p_logs.add_argument("--output", action="store_true", help="Show process stdout/stderr output log")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    db = DatabaseManager()

    if args.subcommand == "run":
        cmd_run(args, db)
    elif args.subcommand == "ps":
        cmd_ps(args, db)
    elif args.subcommand == "inspect":
        cmd_inspect(args, db)
    elif args.subcommand == "stop":
        cmd_stop(args, db)
    elif args.subcommand == "kill":
        cmd_kill(args, db)
    elif args.subcommand == "restart":
        cmd_restart(args, db)
    elif args.subcommand == "rm":
        cmd_rm(args, db)
    elif args.subcommand == "logs":
        cmd_logs(args, db)


if __name__ == "__main__":
    main()
