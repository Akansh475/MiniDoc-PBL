#!/usr/bin/env python3
"""
MiniDocker - Automated Lifecycle, OS & DBMS Test Suite
======================================================
Tests core container lifecycle commands, POSIX signal dispatch,
process supervisor status tracking, relational constraints,
ACID transactions, triggers, and telemetry extraction.
"""

import unittest
import subprocess
import os
import sys
import time
import sqlite3
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLI_PATH = os.path.join(PROJECT_ROOT, "cli", "containeros.py")
DB_PATH = os.path.join(PROJECT_ROOT, "db", "minidocker_local.db")
LOG_DIR = "/tmp/minidocker_logs"


def run_cli(*args):
    """Helper to invoke containeros CLI and capture returncode, stdout, and stderr."""
    cmd = [sys.executable, CLI_PATH] + list(args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


class TestMiniDockerLifecycle(unittest.TestCase):
    """End-to-end integration and system test suite."""

    @classmethod
    def setUpClass(cls):
        # Ensure runtime binary is compiled
        make_res = subprocess.run(["make", "-C", os.path.join(PROJECT_ROOT, "runtime")], capture_output=True)
        if make_res.returncode != 0:
            raise RuntimeError(f"Failed to build runtime: {make_res.stderr.decode()}")

    def setUp(self):
        # Connect to local SQLite DB to verify direct relational state
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def test_01_run_and_status(self):
        """Test container creation, background process launch, and RUNNING state."""
        name = f"test-run-{int(time.time() * 1000) % 100000}"
        ret, out, err = run_cli("run", "sleep 10", "--name", name)
        self.assertEqual(ret, 0, f"run failed: {err}")
        self.assertIn("Container created and running successfully!", out)

        # Extract container ID
        cid = None
        for line in out.splitlines():
            if "Container ID" in line:
                cid = int(line.split(":")[-1].strip())
                break
        self.assertIsNotNone(cid, "Container ID not found in CLI output")

        # Verify DB record
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM containers WHERE container_id = ?", (cid,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["container_name"], name)
        self.assertEqual(row["status"], "RUNNING")
        self.assertEqual(row["user_id"], 1)
        pid = row["pid"]
        self.assertGreater(pid, 0)

        # Verify trigger process_logs
        cur.execute("SELECT action FROM process_logs WHERE container_id = ?", (cid,))
        actions = [r["action"] for r in cur.fetchall()]
        self.assertIn("CONTAINER_CREATED", actions)

        # Cleanup
        run_cli("stop", str(cid))
        run_cli("rm", str(cid))

    def test_02_duplicate_container_name_rollback(self):
        """Test uniqueness constraint violation triggers DB rollback and terminates orphan process."""
        name = f"test-dup-{int(time.time() * 1000) % 100000}"
        ret1, out1, _ = run_cli("run", "sleep 10", "--name", name)
        self.assertEqual(ret1, 0)

        cid1 = None
        for line in out1.splitlines():
            if "Container ID" in line:
                cid1 = int(line.split(":")[-1].strip())
                break

        # Attempt to run with same name
        ret2, out2, err2 = run_cli("run", "sleep 10", "--name", name)
        self.assertNotEqual(ret2, 0, "Duplicate name should have failed")
        self.assertTrue("UNIQUE" in err2 or "Database persistence failed" in err2 or "Rolling back" in err2)

        # Verify only one container exists with this name
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) as cnt FROM containers WHERE container_name = ?", (name,))
        self.assertEqual(cur.fetchone()["cnt"], 1)

        # Cleanup
        if cid1:
            run_cli("stop", str(cid1))
            run_cli("rm", str(cid1))

    def test_03_ps_listing(self):
        """Test listing active vs all containers with table layout."""
        name = f"test-ps-{int(time.time() * 1000) % 100000}"
        ret, out, _ = run_cli("run", "sleep 10", "--name", name)
        self.assertEqual(ret, 0)

        ret_ps, out_ps, _ = run_cli("ps")
        self.assertEqual(ret_ps, 0)
        self.assertIn("ID", out_ps)
        self.assertIn("NAME", out_ps)
        self.assertIn(name, out_ps)

        # Cleanup
        cur = self.conn.cursor()
        cur.execute("SELECT container_id FROM containers WHERE container_name = ?", (name,))
        cid = cur.fetchone()["container_id"]
        run_cli("stop", str(cid))
        run_cli("rm", str(cid))

    def test_04_inspect_and_telemetry(self):
        """Test inspect command prints metadata and records telemetry."""
        name = f"test-inspect-{int(time.time() * 1000) % 100000}"
        ret, out, _ = run_cli("run", "sleep 10", "--name", name, "--cpu", "5")
        self.assertEqual(ret, 0)

        cur = self.conn.cursor()
        cur.execute("SELECT container_id FROM containers WHERE container_name = ?", (name,))
        cid = cur.fetchone()["container_id"]

        ret_ins, out_ins, _ = run_cli("inspect", str(cid))
        self.assertEqual(ret_ins, 0)
        self.assertIn(f"Container Inspection: ID {cid}", out_ins)
        self.assertIn("Telemetry & Resource Usage:", out_ins)
        self.assertIn("Process Alive  : YES", out_ins)

        # Verify usage was recorded in resource_usage
        cur.execute("SELECT count(*) as cnt FROM resource_usage WHERE container_id = ?", (cid,))
        self.assertGreaterEqual(cur.fetchone()["cnt"], 1)

        # Cleanup
        run_cli("stop", str(cid))
        run_cli("rm", str(cid))

    def test_05_stats_command(self):
        """Test stats command displays CPU% and RSS memory in tabular format."""
        name = f"test-stats-{int(time.time() * 1000) % 100000}"
        ret, _, _ = run_cli("run", "sleep 10", "--name", name)
        self.assertEqual(ret, 0)

        ret_st, out_st, _ = run_cli("stats")
        self.assertEqual(ret_st, 0)
        self.assertIn("CPU %", out_st)
        self.assertIn("MEM (MB)", out_st)
        self.assertIn(name, out_st)

        # Cleanup
        cur = self.conn.cursor()
        cur.execute("SELECT container_id FROM containers WHERE container_name = ?", (name,))
        cid = cur.fetchone()["container_id"]
        run_cli("stop", str(cid))
        run_cli("rm", str(cid))

    def test_06_graceful_stop_sigterm_and_kill(self):
        """Test stop with SIGTERM, escalation, and force kill."""
        name = f"test-stop-{int(time.time() * 1000) % 100000}"
        ret, _, _ = run_cli("run", "sleep 20", "--name", name)
        self.assertEqual(ret, 0)

        cur = self.conn.cursor()
        cur.execute("SELECT container_id FROM containers WHERE container_name = ?", (name,))
        cid = cur.fetchone()["container_id"]

        # Stop with SIGTERM
        ret_s, out_s, _ = run_cli("stop", str(cid))
        self.assertEqual(ret_s, 0)
        self.assertIn("stopped", out_s)

        # Check DB status is STOPPED
        cur.execute("SELECT status FROM containers WHERE container_id = ?", (cid,))
        self.assertEqual(cur.fetchone()["status"], "STOPPED")

        # Calling stop on already STOPPED container
        ret_s2, out_s2, _ = run_cli("stop", str(cid))
        self.assertEqual(ret_s2, 0)
        self.assertIn("already STOPPED", out_s2)

        # Restart
        ret_r, out_r, _ = run_cli("restart", str(cid))
        self.assertEqual(ret_r, 0)
        self.assertIn("restarted successfully", out_r)

        # Kill with SIGKILL
        ret_k, out_k, _ = run_cli("kill", str(cid))
        self.assertEqual(ret_k, 0)
        self.assertIn("force killed", out_k)

        # Cleanup
        run_cli("rm", str(cid))

    def test_07_failure_exit_code_detection(self):
        """Test supervisor accurately captures non-zero exit codes and marks state FAILED."""
        name = f"test-fail-{int(time.time() * 1000) % 100000}"
        ret, _, _ = run_cli("run", "sleep 0.1; exit 42", "--name", name)
        self.assertEqual(ret, 0)

        cur = self.conn.cursor()
        cur.execute("SELECT container_id FROM containers WHERE container_name = ?", (name,))
        cid = cur.fetchone()["container_id"]

        # Wait for 0.1s command to finish
        time.sleep(0.3)

        # Reconcile status via ps -a
        run_cli("ps", "-a")

        # Verify DB status is FAILED
        cur.execute("SELECT status FROM containers WHERE container_id = ?", (cid,))
        self.assertEqual(cur.fetchone()["status"], "FAILED")

        # Verify process_logs transition
        cur.execute("SELECT action FROM process_logs WHERE container_id = ? AND new_status = 'FAILED'", (cid,))
        self.assertIsNotNone(cur.fetchone())

        # Cleanup
        run_cli("rm", str(cid))

    def test_08_removal_and_cascading_cleanup(self):
        """Test rm command deletes container, cascades DB records, and removes filesystem logs."""
        name = f"test-rm-{int(time.time() * 1000) % 100000}"
        ret, _, _ = run_cli("run", "sleep 10", "--name", name)
        self.assertEqual(ret, 0)

        cur = self.conn.cursor()
        cur.execute("SELECT container_id, pid FROM containers WHERE container_name = ?", (name,))
        row = cur.fetchone()
        cid = row["container_id"]
        pid = row["pid"]

        log_path = f"{LOG_DIR}/proc_{pid}.log"
        meta_path = f"{LOG_DIR}/proc_{pid}.meta"

        # Record a telemetry metric
        run_cli("inspect", str(cid))

        # Remove container
        ret_rm, out_rm, _ = run_cli("rm", str(cid))
        self.assertEqual(ret_rm, 0)
        self.assertIn("removed successfully and artifacts cleaned", out_rm)

        # Verify container row is gone
        cur.execute("SELECT * FROM containers WHERE container_id = ?", (cid,))
        self.assertIsNone(cur.fetchone())

        # Verify cascade deletion on process_logs & resource_usage
        cur.execute("SELECT count(*) as cnt FROM process_logs WHERE container_id = ?", (cid,))
        self.assertEqual(cur.fetchone()["cnt"], 0)
        cur.execute("SELECT count(*) as cnt FROM resource_usage WHERE container_id = ?", (cid,))
        self.assertEqual(cur.fetchone()["cnt"], 0)

        # Verify filesystem artifacts removed
        self.assertFalse(os.path.exists(log_path), f"Log file {log_path} still exists")
        self.assertFalse(os.path.exists(meta_path), f"Meta file {meta_path} still exists")

    def test_09_invalid_inputs(self):
        """Test CLI error handling on invalid container IDs and subcommands."""
        ret1, _, err1 = run_cli("inspect", "999999")
        self.assertNotEqual(ret1, 0)
        self.assertIn("not found", err1)

        ret2, _, err2 = run_cli("stop", "999999")
        self.assertNotEqual(ret2, 0)
        self.assertIn("not found", err2)

        ret3, _, err3 = run_cli("rm", "999999")
        self.assertNotEqual(ret3, 0)
        self.assertIn("not found", err3)

        ret4, out4, _ = run_cli()
        self.assertEqual(ret4, 0)
        self.assertIn("usage: containeros", out4.lower())


if __name__ == "__main__":
    unittest.main()
