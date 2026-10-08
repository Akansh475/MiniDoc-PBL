/**
 * MiniDocker - Runtime Process Manager Header
 * 
 * Demonstrates Core Operating Systems Concepts:
 * - Process Creation: fork(), execvp()
 * - Process Synchronization: waitpid()
 * - Signals: SIGTERM, SIGKILL
 * - Resource Limiting: setrlimit() (CPU & Memory)
 * - Process Monitoring: PID tracking and /proc or sysctl metrics
 */

#ifndef PROCESS_MANAGER_H
#define PROCESS_MANAGER_H

#include <sys/types.h>
#include <sys/resource.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>

#define MAX_CMD_LEN 1024
#define MAX_ERR_LEN 512
#define DEFAULT_LOG_DIR "/tmp/minidocker_logs"

/* Lifecycle States as defined in academic requirements */
typedef enum {
    STATE_CREATED,
    STATE_RUNNING,
    STATE_STOPPED,
    STATE_EXITED,
    STATE_FAILED
} ProcessState;

/* Resource limits configuration passed to setrlimit */
typedef struct {
    rlim_t cpu_limit_seconds; /* RLIMIT_CPU limit in seconds (0 = unlimited) */
    rlim_t mem_limit_bytes;   /* RLIMIT_AS / RLIMIT_DATA limit in bytes (0 = unlimited) */
} ResourceLimits;

/* Real-time resource metrics */
typedef struct {
    pid_t pid;
    double cpu_usage_pct;     /* CPU percentage */
    double memory_usage_mb;   /* Resident memory in Megabytes */
    bool is_alive;            /* Whether process currently exists */
} ProcessMetrics;

/* Helper conversion functions */
const char* state_to_string(ProcessState state);
ProcessState string_to_state(const char* state_str);

/* Core OS Process Operations */
pid_t launch_process(const char* command, const ResourceLimits* limits, char* error_out, size_t err_len);
bool stop_process(pid_t pid, int sig, char* error_out, size_t err_len);
ProcessState check_process_status(pid_t pid, int* exit_code_out);
bool get_process_metrics(pid_t pid, ProcessMetrics* metrics, char* error_out, size_t err_len);

#endif /* PROCESS_MANAGER_H */
