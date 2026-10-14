"""Build + test workflow. Produces a structured run record from real process results.

Nothing here invents an outcome: a test is PASS only when its program was
executed and the comparison succeeded. Anything that was not executed is
NOT RUN; anything that could not complete (timeout, start failure) is ERROR.
"""

import platform
import secrets
import sys
from datetime import datetime
from pathlib import Path

from . import TOOL_NAME, __version__, compilers, config as config_mod, testcases
from .process import now_iso, run_process

# Test statuses
PASS, FAIL, ERROR, NOT_RUN = "PASS", "FAIL", "ERROR", "NOT RUN"
# Build statuses
BUILD_SUCCESS, BUILD_FAILED, BUILD_ERROR, BUILD_NOT_RUN = "SUCCESS", "FAILED", "ERROR", "NOT RUN"
# Overall statuses
OVERALL = ("PASSED", "PASSED_WITH_SKIPS", "FAILED", "BUILD_FAILED", "NO_TESTS_RUN", "ERROR")


def new_run_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


def summarize(tests):
    counts = {"total": len(tests), "passed": 0, "failed": 0, "errors": 0, "not_run": 0}
    key = {PASS: "passed", FAIL: "failed", ERROR: "errors", NOT_RUN: "not_run"}
    for t in tests:
        counts[key.get(t["status"], "not_run")] += 1
    return counts


def overall_status(build_status, summary, setup_ok=True):
    """Derive the run's overall status from recorded results only."""
    if not setup_ok:
        return "ERROR"
    if build_status != BUILD_SUCCESS:
        return "BUILD_FAILED"
    if summary["failed"] or summary["errors"]:
        return "FAILED"
    executed = summary["passed"]
    if executed == 0:
        return "NO_TESTS_RUN"
    if summary["not_run"]:
        return "PASSED_WITH_SKIPS"
    return "PASSED"


def _not_run(test, reason):
    return {**_test_header(test), "status": NOT_RUN, "actual": None,
            "duration_ms": None, "reasons": [reason]}


def _test_header(test):
    return {k: test[k] for k in ("id", "description", "category", "input", "expected", "compare", "timeout_seconds")}


def run_test(test, program, cwd, default_timeout, max_output):
    """Execute one enabled test case against the built program."""
    timeout = test["timeout_seconds"] or default_timeout
    stdin_text = test["input"] + "\n"
    proc = run_process([str(program)], stdin_text=stdin_text, timeout=timeout,
                       cwd=cwd, max_output_bytes=max_output)
    actual = {"stdout": proc["stdout"], "stderr": proc["stderr"], "exit_code": proc["exit_code"],
              "timed_out": proc["timed_out"], "truncated": proc["truncated"]}
    entry = {**_test_header(test), "timeout_seconds": timeout, "actual": actual,
             "duration_ms": proc["duration_ms"]}
    if proc["error"]:
        entry.update(status=ERROR, reasons=[proc["error"]])
        return entry
    passed, reasons = testcases.compare(test, proc["stdout"], proc["exit_code"])
    entry.update(status=PASS if passed else FAIL, reasons=reasons)
    return entry


def compiler_version(adapter, executable, max_output):
    if not adapter.version_args:
        return "not collected for this adapter"
    proc = run_process([executable, *adapter.version_args], timeout=10, max_output_bytes=max_output)
    if proc["error"] or proc["exit_code"] != 0:
        return "unavailable"
    first = proc["stdout"].strip().splitlines()
    return first[0] if first else "unavailable"


def execute_run(cfg, root=config_mod.PROJECT_ROOT, run_id=None, on_progress=None):
    """Validate, build and test according to ``cfg``; return the full run record."""
    progress = on_progress or (lambda message: None)
    run = {
        "run_id": run_id or new_run_id(),
        "tool": {"name": TOOL_NAME, "version": __version__},
        "project_name": cfg["project_name"],
        "started_at": now_iso(), "ended_at": None,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "compiler_version": None,
        },
        "config": cfg,
        "checks": [],
        "build": {"status": BUILD_NOT_RUN, "command": None, "exit_code": None, "stdout": "", "stderr": "",
                  "duration_ms": None, "timed_out": False, "error": None, "output_file": None},
        "suite": None,
        "tests": [],
        "notes": [],
    }
    max_output = cfg["run"]["max_output_bytes"]

    progress("Validating configuration")
    checks = config_mod.validate_environment(cfg, root)
    run["checks"] = checks
    blocking = [c for c in checks if c["status"] == "error" and c["name"] != "Compiler executable"]
    suite = None
    if not blocking:
        paths = config_mod.resolved_paths(cfg, root)
        suite = testcases.load_suite(paths["tests_file"])
        run["suite"] = suite["suite"]

    if blocking:
        run["notes"].append("Setup errors prevented the build and all tests: "
                            + "; ".join(c["message"] for c in blocking))
        return _finish(run, setup_ok=False)

    adapter = compilers.ADAPTERS[cfg["compiler"]["adapter"]]
    executable = cfg["compiler"]["executable"]
    exe_path = config_mod.find_executable(executable, root) or executable
    build_dir = paths["build_dir"]
    build_dir.mkdir(parents=True, exist_ok=True)
    output = build_dir / compilers.executable_name(paths["source_file"].stem)
    # Remove only our own previous build output so a failed compile can never run a stale binary.
    if output.is_file():
        output.unlink()

    command = adapter.build_command(exe_path, cfg["compiler"]["args"], paths["source_file"], output)
    progress("Compiling " + paths["source_file"].name)
    proc = run_process(command, timeout=cfg["compiler"]["timeout_seconds"],
                       cwd=paths["source_dir"], max_output_bytes=max_output)
    build = run["build"]
    build.update(command=command, exit_code=proc["exit_code"], stdout=proc["stdout"], stderr=proc["stderr"],
                 duration_ms=proc["duration_ms"], timed_out=proc["timed_out"], error=proc["error"],
                 output_file=str(output))
    if proc["error"]:
        build["status"] = BUILD_ERROR
    elif proc["exit_code"] != 0:
        build["status"] = BUILD_FAILED
    elif not output.is_file():
        build["status"] = BUILD_FAILED
        build["error"] = f"Compiler exited with 0 but did not produce {output}"
    else:
        build["status"] = BUILD_SUCCESS
    if build["status"] != BUILD_ERROR:
        run["environment"]["compiler_version"] = compiler_version(adapter, exe_path, max_output)

    if build["status"] != BUILD_SUCCESS:
        reason = f"Build {build['status'].lower()}: test not executed"
        run["tests"] = [_not_run(t, reason) for t in suite["tests"]]
        run["notes"].append("No tests were executed because the build did not succeed.")
        return _finish(run)

    total = len(suite["tests"])
    for index, test in enumerate(suite["tests"], start=1):
        if not test["enabled"]:
            run["tests"].append(_not_run(test, "Disabled in test file"
                                         + (f": {test['skip_reason']}" if test["skip_reason"] else "")))
            continue
        progress(f"Running {test['id']} ({index}/{total})")
        run["tests"].append(run_test(test, output, build_dir,
                                     cfg["run"]["default_test_timeout_seconds"], max_output))
    return _finish(run)


def _finish(run, setup_ok=True):
    run["summary"] = summarize(run["tests"])
    run["status"] = overall_status(run["build"]["status"], run["summary"], setup_ok)
    if run["summary"]["not_run"]:
        run["notes"].append(f"{run['summary']['not_run']} test(s) were not run; they are not counted as passed.")
    run["ended_at"] = now_iso()
    return run
