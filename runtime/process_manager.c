/**
 * MiniDocker - Runtime Process Manager Implementation
 * 
 * Operating System Concepts Implemented:
 * 1. Process Creation: fork() + exec() with setsid() daemon detachment
 * 2. Process Synchronization: waitpid() with WNOHANG and status checking
 * 3. Inter-Process Signals: kill() using SIGTERM (graceful) and SIGKILL (forced)
 * 4. Resource Limits: setrlimit() for RLIMIT_CPU and RLIMIT_AS (Address Space)
 * 5. Pipe Communication: O_CLOEXEC pipe for synchronous error detection across exec
 * 6. Process Monitoring: ps / proc polling for CPU% and Resident Memory (RSS)
 */

#include "process_manager.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <sys/time.h>

/* Convert ProcessState enum to uppercase string */
const char* state_to_string(ProcessState state) {
    switch (state) {
        case STATE_CREATED: return "CREATED";
        case STATE_RUNNING: return "RUNNING";
        case STATE_STOPPED: return "STOPPED";
        case STATE_EXITED:  return "EXITED";
        case STATE_FAILED:  return "FAILED";
        default:            return "UNKNOWN";
    }
}

/* Convert string to ProcessState enum */
ProcessState string_to_state(const char* state_str) {
    if (!state_str) return STATE_FAILED;
    if (strcmp(state_str, "CREATED") == 0) return STATE_CREATED;
    if (strcmp(state_str, "RUNNING") == 0) return STATE_RUNNING;
    if (strcmp(state_str, "STOPPED") == 0) return STATE_STOPPED;
    if (strcmp(state_str, "EXITED") == 0)  return STATE_EXITED;
    if (strcmp(state_str, "FAILED") == 0)  return STATE_FAILED;
    return STATE_FAILED;
}

/* Strip trailing newline if any */
static void trim_newline(char* str) {
    if (!str) return;
    size_t len = strlen(str);
    while (len > 0 && (str[len - 1] == '\n' || str[len - 1] == '\r')) {
        str[len - 1] = '\0';
        len--;
    }
}

/* Ensure directory exists for logging child processes */
static void ensure_log_dir() {
    struct stat st = {0};
    if (stat(DEFAULT_LOG_DIR, &st) == -1) {
        mkdir(DEFAULT_LOG_DIR, 0755);
    }
}

/**
 * Launch a background command with resource limits.
 * Uses pipe with FD_CLOEXEC to synchronously catch exec errors.
 */
pid_t launch_process(const char* command, const ResourceLimits* limits, char* error_out, size_t err_len) {
    if (!command || strlen(command) == 0) {
        snprintf(error_out, err_len, "Command string cannot be empty");
        return -1;
    }

    ensure_log_dir();

    // Pipe for communicating execvp failure from child to parent
    int exec_pipe[2];
    if (pipe(exec_pipe) < 0) {
        snprintf(error_out, err_len, "Failed to create error pipe: %s", strerror(errno));
        return -1;
    }

    // Set close-on-exec on write-end so pipe closes automatically if exec succeeds
    int flags = fcntl(exec_pipe[1], F_GETFD);
    if (flags >= 0) {
        fcntl(exec_pipe[1], F_SETFD, flags | FD_CLOEXEC);
    }

    pid_t pid = fork();

    if (pid < 0) {
        // Fork failed
        snprintf(error_out, err_len, "fork() failed: %s", strerror(errno));
        close(exec_pipe[0]);
        close(exec_pipe[1]);
        return -1;
    }

    if (pid == 0) {
        // ==========================================
        // CHILD PROCESS
        // ==========================================
        close(exec_pipe[0]); // Close unused read-end

        // 1. Create a new session to detach from parent terminal
        setsid();

        // 2. Apply CPU Resource Limit via setrlimit()
        if (limits && limits->cpu_limit_seconds > 0) {
            struct rlimit rl_cpu;
            rl_cpu.rlim_cur = limits->cpu_limit_seconds;
            rl_cpu.rlim_max = limits->cpu_limit_seconds;
            if (setrlimit(RLIMIT_CPU, &rl_cpu) != 0) {
                // Warning, but proceed
            }
        }

        // 3. Apply Memory Resource Limit via setrlimit()
        if (limits && limits->mem_limit_bytes > 0) {
            struct rlimit rl_mem;
            rl_mem.rlim_cur = limits->mem_limit_bytes;
            rl_mem.rlim_max = limits->mem_limit_bytes;
#if defined(RLIMIT_AS)
            setrlimit(RLIMIT_AS, &rl_mem);
#elif defined(RLIMIT_DATA)
            setrlimit(RLIMIT_DATA, &rl_mem);
#endif
        }

        // 4. Redirect standard input to /dev/null
        int devnull = open("/dev/null", O_RDONLY);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            close(devnull);
        }

        // 5. Redirect stdout & stderr to log file: /tmp/minidocker_logs/proc_<PID>.log
        char log_path[256];
        snprintf(log_path, sizeof(log_path), "%s/proc_%d.log", DEFAULT_LOG_DIR, getpid());
        int log_fd = open(log_path, O_WRONLY | O_CREAT | O_APPEND, 0644);
        if (log_fd >= 0) {
            dup2(log_fd, STDOUT_FILENO);
            dup2(log_fd, STDERR_FILENO);
            close(log_fd);
        }

        // 6. Execute command using POSIX shell
        execl("/bin/sh", "sh", "-c", command, (char *)NULL);

        // If exec fails, send errno through pipe to parent and exit
        int err = errno;
        write(exec_pipe[1], &err, sizeof(err));
        close(exec_pipe[1]);
        _exit(127);
    }

    // ==========================================
    // PARENT PROCESS
    // ==========================================
    close(exec_pipe[1]); // Close unused write-end

    // Read error code from child (if exec failed)
    int child_errno = 0;
    ssize_t bytes_read = read(exec_pipe[0], &child_errno, sizeof(child_errno));
    close(exec_pipe[0]);

    if (bytes_read > 0 && child_errno != 0) {
        // Child failed during exec
        snprintf(error_out, err_len, "Child exec() failed: %s", strerror(child_errno));
        int status;
        waitpid(pid, &status, 0); // Reap zombie
        return -1;
    }

    // Small delay to verify child didn't crash instantaneously
    usleep(50000); // 50ms

    int status;
    pid_t result = waitpid(pid, &status, WNOHANG);
    if (result == pid) {
        if (WIFEXITED(status) && WEXITSTATUS(status) != 0) {
            snprintf(error_out, err_len, "Process exited immediately with code %d", WEXITSTATUS(status));
            return -1;
        } else if (WIFSIGNALED(status)) {
            snprintf(error_out, err_len, "Process terminated immediately by signal %d", WTERMSIG(status));
            return -1;
        }
    }

    return pid;
}

/**
 * Stop or Kill a process using POSIX signals (SIGTERM or SIGKILL).
 */
bool stop_process(pid_t pid, int sig, char* error_out, size_t err_len) {
    if (pid <= 1) {
        snprintf(error_out, err_len, "Refusing to send signal to system PID %d", pid);
        return false;
    }

    if (kill(pid, sig) != 0) {
        if (errno == ESRCH) {
            snprintf(error_out, err_len, "Process PID %d does not exist (already dead)", pid);
        } else if (errno == EPERM) {
            snprintf(error_out, err_len, "Permission denied to signal PID %d", pid);
        } else {
            snprintf(error_out, err_len, "Signal %d failed: %s", sig, strerror(errno));
        }
        return false;
    }

    // Give process brief moment to terminate and reap if child
    int status;
    waitpid(pid, &status, WNOHANG);
    return true;
}

/**
 * Check process state.
 * Returns RUNNING, STOPPED, EXITED, or FAILED.
 */
ProcessState check_process_status(pid_t pid, int* exit_code_out) {
    if (exit_code_out) *exit_code_out = 0;
    if (pid <= 0) return STATE_FAILED;

    int status;
    pid_t wait_res = waitpid(pid, &status, WNOHANG);

    if (wait_res == pid) {
        if (WIFEXITED(status)) {
            int code = WEXITSTATUS(status);
            if (exit_code_out) *exit_code_out = code;
            return (code == 0) ? STATE_EXITED : STATE_FAILED;
        } else if (WIFSIGNALED(status)) {
            int sig = WTERMSIG(status);
            if (exit_code_out) *exit_code_out = 128 + sig;
            return STATE_STOPPED;
        }
    }

    // If waitpid returned 0 (still running) or -1 with ECHILD (not a direct child)
    // Check existence via kill(pid, 0)
    if (kill(pid, 0) == 0) {
        return STATE_RUNNING;
    } else {
        if (errno == ESRCH) {
            // Process no longer exists in OS process table
            return STATE_EXITED;
        } else if (errno == EPERM) {
            // Process exists but belongs to another user
            return STATE_RUNNING;
        }
    }

    return STATE_FAILED;
}

/**
 * Query real-time CPU % and Resident Memory (RSS in MB) using ps.
 */
bool get_process_metrics(pid_t pid, ProcessMetrics* metrics, char* error_out, size_t err_len) {
    if (!metrics) return false;
    metrics->pid = pid;
    metrics->cpu_usage_pct = 0.0;
    metrics->memory_usage_mb = 0.0;
    metrics->is_alive = false;

    if (kill(pid, 0) != 0) {
        if (errno == ESRCH) {
            metrics->is_alive = false;
            return true;
        }
    }

    metrics->is_alive = true;

    char cmd[128];
    snprintf(cmd, sizeof(cmd), "ps -p %d -o %%cpu=,rss=", pid);
    FILE* fp = popen(cmd, "r");
    if (!fp) {
        snprintf(error_out, err_len, "Failed to execute ps for PID %d", pid);
        return false;
    }

    double cpu = 0.0;
    long rss_kb = 0;
    if (fscanf(fp, "%lf %ld", &cpu, &rss_kb) == 2) {
        metrics->cpu_usage_pct = cpu;
        metrics->memory_usage_mb = (double)rss_kb / 1024.0;
    }
    pclose(fp);

    return true;
}

/* CLI command dispatcher returning structured JSON */
int main(int argc, char* argv[]) {
    if (argc < 2) {
        printf("{\n  \"error\": \"Usage: %s <run|status|stop|kill|restart|metrics> [args...]\"\n}\n", argv[0]);
        return 1;
    }

    const char* action = argv[1];
    char error_buf[MAX_ERR_LEN] = {0};

    if (strcmp(action, "run") == 0) {
        // Usage: process_manager run <cpu_limit_sec> <mem_limit_bytes> "<command>"
        if (argc < 5) {
            printf("{\n  \"status\": \"FAILED\",\n  \"error\": \"Missing arguments: run <cpu_sec> <mem_bytes> <cmd>\"\n}\n");
            return 1;
        }

        ResourceLimits limits;
        limits.cpu_limit_seconds = (rlim_t)strtoul(argv[2], NULL, 10);
        limits.mem_limit_bytes = (rlim_t)strtoull(argv[3], NULL, 10);
        const char* command = argv[4];

        pid_t pid = launch_process(command, &limits, error_buf, sizeof(error_buf));

        if (pid > 0) {
            printf("{\n");
            printf("  \"pid\": %d,\n", pid);
            printf("  \"status\": \"RUNNING\",\n");
            printf("  \"cpu_limit\": %lu,\n", (unsigned long)limits.cpu_limit_seconds);
            printf("  \"memory_limit\": %llu,\n", (unsigned long long)limits.mem_limit_bytes);
            printf("  \"log_file\": \"%s/proc_%d.log\"\n", DEFAULT_LOG_DIR, pid);
            printf("}\n");
            return 0;
        } else {
            printf("{\n");
            printf("  \"pid\": -1,\n");
            printf("  \"status\": \"FAILED\",\n");
            printf("  \"error\": \"%s\"\n", error_buf[0] ? error_buf : "Failed to spawn process");
            printf("}\n");
            return 1;
        }
    } else if (strcmp(action, "status") == 0) {
        // Usage: process_manager status <pid>
        if (argc < 3) {
            printf("{\n  \"error\": \"Missing PID for status\"\n}\n");
            return 1;
        }
        pid_t pid = (pid_t)atoi(argv[2]);
        int exit_code = 0;
        ProcessState state = check_process_status(pid, &exit_code);

        printf("{\n");
        printf("  \"pid\": %d,\n", pid);
        printf("  \"status\": \"%s\",\n", state_to_string(state));
        printf("  \"is_alive\": %s,\n", (state == STATE_RUNNING) ? "true" : "false");
        printf("  \"exit_code\": %d\n", exit_code);
        printf("}\n");
        return 0;
    } else if (strcmp(action, "stop") == 0) {
        // Usage: process_manager stop <pid>
        if (argc < 3) {
            printf("{\n  \"error\": \"Missing PID for stop\"\n}\n");
            return 1;
        }
        pid_t pid = (pid_t)atoi(argv[2]);
        bool ok = stop_process(pid, SIGTERM, error_buf, sizeof(error_buf));
        trim_newline(error_buf);

        printf("{\n");
        printf("  \"pid\": %d,\n", pid);
        printf("  \"status\": \"%s\",\n", ok ? "STOPPED" : "FAILED");
        printf("  \"signal\": \"SIGTERM\",\n");
        printf("  \"success\": %s%s%s%s\n",
               ok ? "true" : "false",
               ok ? "" : ",\n  \"error\": \"",
               ok ? "" : error_buf,
               ok ? "" : "\"");
        printf("}\n");
        return ok ? 0 : 1;
    } else if (strcmp(action, "kill") == 0) {
        // Usage: process_manager kill <pid>
        if (argc < 3) {
            printf("{\n  \"error\": \"Missing PID for kill\"\n}\n");
            return 1;
        }
        pid_t pid = (pid_t)atoi(argv[2]);
        bool ok = stop_process(pid, SIGKILL, error_buf, sizeof(error_buf));
        trim_newline(error_buf);

        printf("{\n");
        printf("  \"pid\": %d,\n", pid);
        printf("  \"status\": \"%s\",\n", ok ? "STOPPED" : "FAILED");
        printf("  \"signal\": \"SIGKILL\",\n");
        printf("  \"success\": %s%s%s%s\n",
               ok ? "true" : "false",
               ok ? "" : ",\n  \"error\": \"",
               ok ? "" : error_buf,
               ok ? "" : "\"");
        printf("}\n");
        return ok ? 0 : 1;
    } else if (strcmp(action, "restart") == 0) {
        // Usage: process_manager restart <old_pid> <cpu_sec> <mem_bytes> "<command>"
        if (argc < 6) {
            printf("{\n  \"status\": \"FAILED\",\n  \"error\": \"Missing args: restart <old_pid> <cpu> <mem> <cmd>\"\n}\n");
            return 1;
        }
        pid_t old_pid = (pid_t)atoi(argv[2]);
        ResourceLimits limits;
        limits.cpu_limit_seconds = (rlim_t)strtoul(argv[3], NULL, 10);
        limits.mem_limit_bytes = (rlim_t)strtoull(argv[4], NULL, 10);
        const char* command = argv[5];

        // 1. Terminate old process if still alive
        if (old_pid > 1 && kill(old_pid, 0) == 0) {
            stop_process(old_pid, SIGTERM, error_buf, sizeof(error_buf));
            usleep(100000); // 100ms
            if (kill(old_pid, 0) == 0) {
                stop_process(old_pid, SIGKILL, error_buf, sizeof(error_buf));
            }
        }

        // 2. Launch new process
        pid_t new_pid = launch_process(command, &limits, error_buf, sizeof(error_buf));
        if (new_pid > 0) {
            printf("{\n");
            printf("  \"old_pid\": %d,\n", old_pid);
            printf("  \"pid\": %d,\n", new_pid);
            printf("  \"status\": \"RUNNING\",\n");
            printf("  \"success\": true,\n");
            printf("  \"log_file\": \"%s/proc_%d.log\"\n", DEFAULT_LOG_DIR, new_pid);
            printf("}\n");
            return 0;
        } else {
            printf("{\n");
            printf("  \"old_pid\": %d,\n", old_pid);
            printf("  \"pid\": -1,\n");
            printf("  \"status\": \"FAILED\",\n");
            printf("  \"error\": \"%s\"\n", error_buf[0] ? error_buf : "Failed to restart");
            printf("}\n");
            return 1;
        }
    } else if (strcmp(action, "metrics") == 0) {
        // Usage: process_manager metrics <pid>
        if (argc < 3) {
            printf("{\n  \"error\": \"Missing PID for metrics\"\n}\n");
            return 1;
        }
        pid_t pid = (pid_t)atoi(argv[2]);
        ProcessMetrics metrics;
        bool ok = get_process_metrics(pid, &metrics, error_buf, sizeof(error_buf));

        if (ok) {
            printf("{\n");
            printf("  \"pid\": %d,\n", pid);
            printf("  \"cpu_usage_pct\": %.2f,\n", metrics.cpu_usage_pct);
            printf("  \"memory_usage_mb\": %.2f,\n", metrics.memory_usage_mb);
            printf("  \"is_alive\": %s\n", metrics.is_alive ? "true" : "false");
            printf("}\n");
            return 0;
        } else {
            printf("{\n  \"pid\": %d,\n  \"error\": \"%s\"\n}\n", pid, error_buf);
            return 1;
        }
    } else {
        printf("{\n  \"error\": \"Unknown action '%s'\"\n}\n", action);
        return 1;
    }
}
