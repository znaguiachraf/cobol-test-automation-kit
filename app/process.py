"""Safe process execution.

Every external process is started from an argument list (never a shell
string), with a timeout, in its own process group so the whole tree can be
killed on timeout, and with stdout/stderr captured to temporary files and
truncated to a byte limit.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

TRUNCATION_NOTE = "\n[... output truncated by COBOL Test Automation Kit ...]\n"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_limited(fh, limit):
    fh.seek(0)
    data = fh.read(limit + 1)
    truncated = len(data) > limit
    text = data[:limit].decode("utf-8", errors="replace")
    return (text + TRUNCATION_NOTE if truncated else text), truncated


def _kill_tree(proc):
    try:
        if sys.platform.startswith("win"):
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_process(args, stdin_text="", timeout=10, cwd=None, max_output_bytes=65536):
    """Run ``args`` (a list) and return a result dict. Never raises for process problems.

    Result keys: args, cwd, started_at, ended_at, duration_ms, exit_code
    (None if not started or killed), stdout, stderr, timed_out, error,
    truncated.
    """
    if not isinstance(args, (list, tuple)) or not args or not all(isinstance(a, str) for a in args):
        raise TypeError("args must be a non-empty list of strings")
    result = {
        "args": list(args), "cwd": str(cwd) if cwd else None,
        "started_at": now_iso(), "ended_at": None, "duration_ms": 0,
        "exit_code": None, "stdout": "", "stderr": "",
        "timed_out": False, "error": None, "truncated": False,
    }
    start = time.monotonic()
    with tempfile.TemporaryFile() as out_fh, tempfile.TemporaryFile() as err_fh:
        try:
            proc = subprocess.Popen(
                list(args), cwd=cwd, stdin=subprocess.PIPE, stdout=out_fh, stderr=err_fh,
                shell=False, start_new_session=not sys.platform.startswith("win"),
            )
        except FileNotFoundError:
            result["error"] = f"Executable not found: {args[0]}"
        except PermissionError:
            result["error"] = f"Permission denied when starting: {args[0]}"
        except OSError as exc:
            result["error"] = f"Could not start process: {exc}"
        else:
            try:
                proc.communicate(input=stdin_text.encode("utf-8"), timeout=timeout)
                result["exit_code"] = proc.returncode
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                proc.wait()
                result["timed_out"] = True
                result["error"] = f"Timed out after {timeout} s; process was terminated"
            except BrokenPipeError:
                # Program exited without reading stdin; its exit code still counts.
                proc.wait()
                result["exit_code"] = proc.returncode
        result["stdout"], t1 = _read_limited(out_fh, max_output_bytes)
        result["stderr"], t2 = _read_limited(err_fh, max_output_bytes)
        result["truncated"] = t1 or t2
    result["duration_ms"] = int((time.monotonic() - start) * 1000)
    result["ended_at"] = now_iso()
    return result
