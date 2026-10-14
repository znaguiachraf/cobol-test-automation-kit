"""Persistence of run records as JSON files in ``runs/``."""

import json
import os
import re
import tempfile
from pathlib import Path

from .config import PROJECT_ROOT

RUNS_DIR = PROJECT_ROOT / "runs"
RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def valid_run_id(run_id):
    return isinstance(run_id, str) and bool(RUN_ID_PATTERN.match(run_id))


def save_run(run, runs_dir=RUNS_DIR):
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=runs_dir, prefix=".run-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(run, fh, indent=2)
    os.replace(tmp, runs_dir / f"{run['run_id']}.json")


def load_run(run_id, runs_dir=RUNS_DIR):
    if not valid_run_id(run_id):
        return None
    path = Path(runs_dir) / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text("utf-8"))


def list_runs(runs_dir=RUNS_DIR, limit=50):
    """Newest-first summaries of stored runs."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    ids = sorted((p.stem for p in runs_dir.glob("*.json") if valid_run_id(p.stem)), reverse=True)
    out = []
    for run_id in ids[:limit]:
        try:
            run = load_run(run_id, runs_dir)
        except (OSError, ValueError):
            continue
        out.append({k: run.get(k) for k in ("run_id", "started_at", "ended_at", "status", "summary", "report_file")}
                   | {"build_status": run.get("build", {}).get("status")})
    return out
