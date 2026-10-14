"""Run orchestration shared by the web server and the CLI: run, report, persist."""

import threading
import traceback
from pathlib import Path

from . import config as config_mod, report, runner, store


def run_and_record(cfg, root=config_mod.PROJECT_ROOT, runs_dir=store.RUNS_DIR, run_id=None, on_progress=None):
    """Execute a run, write its HTML report and store the record. Returns the run dict."""
    run = runner.execute_run(cfg, root=root, run_id=run_id, on_progress=on_progress)
    try:
        report_dir = config_mod.resolved_paths(cfg, root)["report_dir"]
        path = report.write_report(run, report_dir, root=root)
        run["report_file"] = str(path)
    except (config_mod.ConfigError, OSError) as exc:
        run["report_file"] = None
        run["notes"].append(f"HTML report could not be written: {exc}")
    store.save_run(run, runs_dir)
    return run


def report_path_for(run, root=config_mod.PROJECT_ROOT):
    """Return the report file of a stored run if it is the expected file inside the project."""
    name = run.get("report_file")
    if not name:
        return None
    path = config_mod.resolve_in_root(root, name)
    if path is None or path.name != f"report-{run['run_id']}.html" or not path.is_file():
        return None
    return path


class RunManager:
    """Runs one build/test workflow at a time in a background thread."""

    def __init__(self, root=config_mod.PROJECT_ROOT, runs_dir=store.RUNS_DIR):
        self.root, self.runs_dir = Path(root), Path(runs_dir)
        self._lock = threading.Lock()
        self.state = {"running": False, "run_id": None, "message": "Idle", "error": None}

    def status(self):
        with self._lock:
            return dict(self.state)

    def start(self, cfg):
        """Start a run; returns the run id, or None if a run is already in progress."""
        with self._lock:
            if self.state["running"]:
                return None
            run_id = runner.new_run_id()
            self.state = {"running": True, "run_id": run_id, "message": "Starting", "error": None}
        threading.Thread(target=self._work, args=(cfg, run_id), daemon=True).start()
        return run_id

    def _progress(self, message):
        with self._lock:
            self.state["message"] = message

    def _work(self, cfg, run_id):
        error = None
        try:
            run_and_record(cfg, self.root, self.runs_dir, run_id=run_id, on_progress=self._progress)
        except Exception as exc:  # recorded and shown in the UI; never reported as a pass
            traceback.print_exc()
            error = f"Run failed unexpectedly: {exc}"
        with self._lock:
            self.state.update(running=False, message="Finished" if not error else "Failed", error=error)
