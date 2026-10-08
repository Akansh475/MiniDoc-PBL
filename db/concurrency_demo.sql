-- ============================================================================
-- MiniDocker - Concurrency & Row Locking Demonstration (Oracle SQL)
-- ============================================================================
-- Academic Viva Demonstration:
-- Focus: Pessimistic Concurrency Control, ACID Isolation, and Row Locks
-- Feature: SELECT ... FOR UPDATE
-- 
-- SCENARIO:
-- Two concurrent database transactions (Session A and Session B) attempt
-- to modify the status of the same container record (Container ID: 1).
-- 
-- How to run this during Viva:
-- Open two terminal windows or two SQL*Plus / SQL Developer connections:
-- Terminal 1 -> SESSION A
-- Terminal 2 -> SESSION B
-- Follow the chronological steps below.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- STEP 0: INITIAL VERIFICATION (Run in any session)
-- ----------------------------------------------------------------------------
SELECT container_id, container_name, status, pid, updated_at
  FROM containers
 WHERE container_id = 1;

-- Expected output: status = 'RUNNING'


-- ----------------------------------------------------------------------------
-- STEP 1: SESSION A ACQUIRES EXCLUSIVE ROW LOCK
-- ----------------------------------------------------------------------------
-- Run in SESSION A:
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- Acquire row-level exclusive lock on container 1
SELECT container_id, container_name, status, pid
  FROM containers
 WHERE container_id = 1
   FOR UPDATE;

-- EXPLANATION FOR VIVA:
-- Oracle places an exclusive TX (Transaction) lock on row 1 in the data block.
-- The row's lock byte in the block header is set to Session A's transaction table slot.
-- Other sessions can still SELECT the unmodified committed data (Non-blocking reads / MVCC).
-- But no other session can UPDATE, DELETE, or SELECT ... FOR UPDATE this row.


-- ----------------------------------------------------------------------------
-- STEP 2: SESSION B ATTEMPTS TO LOCK THE SAME ROW (BLOCKED / WAITING)
-- ----------------------------------------------------------------------------
-- Run in SESSION B:
SELECT container_id, container_name, status, pid
  FROM containers
 WHERE container_id = 1
   FOR UPDATE;

-- OBSERVE:
-- Session B HANGS / WAITS!
-- Oracle places Session B into the enqueue wait queue (event: 'enq: TX - row lock contention').
-- Session B will not proceed until Session A either COMMITs or ROLLBACKs.


-- ----------------------------------------------------------------------------
-- STEP 3: VIVA INSPECTION - EXAMINE ORACLE LOCK QUEUE (Run in SESSION A or SYS)
-- ----------------------------------------------------------------------------
-- Run in SESSION A (or DBA session):
SELECT 
    s.sid,
    s.serial#,
    s.username,
    s.status,
    s.event,
    l.type AS lock_type,
    l.lmode AS lock_mode_held,
    l.request AS lock_mode_requested
FROM v$session s
JOIN v$lock l ON s.sid = l.sid
WHERE l.type = 'TX'
ORDER BY s.sid;

-- EXPLANATION FOR VIVA:
-- Session A holds lmode = 6 (Exclusive Lock).
-- Session B requests request = 6 (Exclusive Lock) and is waiting in the queue.


-- ----------------------------------------------------------------------------
-- STEP 4: SESSION A PERFORMS UPDATE AND COMMITS
-- ----------------------------------------------------------------------------
-- Run in SESSION A:
UPDATE containers
   SET status = 'STOPPED',
       updated_at = SYSTIMESTAMP
 WHERE container_id = 1;

-- Notice: Session B is STILL WAITING because Session A has not released the lock.

-- Now release lock by committing the transaction:
COMMIT;

-- OBSERVE SESSION B IMMEDIATELY:
-- As soon as Session A executes COMMIT, Session B immediately UNBLOCKS!
-- Session B now acquires the exclusive lock on Container 1 and displays the row.
-- Notice that Session B sees the newly committed status: 'STOPPED'!


-- ----------------------------------------------------------------------------
-- STEP 5: SESSION B PERFORMS ALTERNATIVE UPDATE OR ROLLBACK
-- ----------------------------------------------------------------------------
-- Run in SESSION B:
-- Session B can now perform its operation or rollback:
ROLLBACK;

-- Transaction completed cleanly with zero data corruption or race conditions.


-- ----------------------------------------------------------------------------
-- STEP 6: ALTERNATIVE VARIATION - SELECT FOR UPDATE NOWAIT
-- ----------------------------------------------------------------------------
-- If an application cannot afford to wait indefinitely, Oracle supports:
-- SELECT ... FOR UPDATE NOWAIT
-- or
-- SELECT ... FOR UPDATE WAIT <seconds>

-- Demonstration:
-- Session A:
SELECT * FROM containers WHERE container_id = 1 FOR UPDATE;

-- Session B:
-- SELECT * FROM containers WHERE container_id = 1 FOR UPDATE NOWAIT;
-- Result: ORA-00054: resource busy and acquire with NOWAIT specified or timeout expired
-- Session A:
ROLLBACK;
