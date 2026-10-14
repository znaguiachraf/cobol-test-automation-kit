"""Configuration model: loading, normalisation, validation and saving.

The JSON config file is the single source of truth for the compiler,
its arguments, the source/build/test/report paths and timeouts.
"""

import copy
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path

from . import compilers, testcases

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "kit.config.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "kit.config.example.json"

MAX_STRING = 500
MAX_ARGS = 50
TIMEOUT_RANGE = (1, 3600)
OUTPUT_LIMIT_RANGE = (1024, 10 * 1024 * 1024)

DEFAULT_CONFIG = {
    "project_name": "PREMCALC demo",
    "compiler": {
        "adapter": "gnucobol",
        "executable": "cobc",
        "args": ["-x", "-free", "-Wall"],
        "timeout_seconds": 60,
    },
    "paths": {
        "source_dir": "samples/src",
        "source_file": "PREMCALC.cbl",
        "build_dir": "build",
        "tests_file": "samples/tests/premcalc_tests.json",
        "report_dir": "reports",
    },
    "run": {
        "default_test_timeout_seconds": 5,
        "max_output_bytes": 65536,
    },
}

PATH_KEYS = ("source_dir", "source_file", "build_dir", "tests_file", "report_dir")


class ConfigError(ValueError):
    """Raised when a configuration cannot be normalised. Carries a list of messages."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def _clean_string(value, field, errors, allow_empty=False):
    if not isinstance(value, str):
        errors.append(f"{field}: must be a string")
        return ""
    value = value.strip()
    if not value and not allow_empty:
        errors.append(f"{field}: is required")
    if len(value) > MAX_STRING:
        errors.append(f"{field}: longer than {MAX_STRING} characters")
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        errors.append(f"{field}: must not contain NUL or line-break characters")
    return value


def _clean_int(value, field, bounds, errors):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        errors.append(f"{field}: must be a whole number")
        return bounds[0]
    try:
        number = int(str(value).strip())
    except ValueError:
        errors.append(f"{field}: must be a whole number")
        return bounds[0]
    if not bounds[0] <= number <= bounds[1]:
        errors.append(f"{field}: must be between {bounds[0]} and {bounds[1]}")
    return number


def parse_args_text(text):
    """Split a flags text field into an argument list using POSIX shell quoting rules.

    Only splitting is done - no variable expansion, globbing or command
    substitution - and the result is never passed to a shell.
    """
    try:
        return shlex.split(text, posix=True)
    except ValueError as exc:
        raise ConfigError([f"compiler.args: cannot parse flags ({exc})"])


def normalize(raw):
    """Return a clean config dict built from untrusted input, or raise ConfigError.

    Accepts ``compiler.args`` as a list of strings, or ``compiler.args_text``
    as a single string split with :func:`parse_args_text`.
    """
    if not isinstance(raw, dict):
        raise ConfigError(["config: must be a JSON object"])
    errors = []
    compiler_raw = raw.get("compiler") or {}
    paths_raw = raw.get("paths") or {}
    run_raw = raw.get("run") or {}
    if not all(isinstance(x, dict) for x in (compiler_raw, paths_raw, run_raw)):
        raise ConfigError(["config: 'compiler', 'paths' and 'run' must be objects"])

    cfg = default_config()
    cfg["project_name"] = _clean_string(raw.get("project_name", cfg["project_name"]), "project_name", errors)

    adapter = _clean_string(compiler_raw.get("adapter", "gnucobol"), "compiler.adapter", errors)
    if adapter and adapter not in compilers.ADAPTERS:
        errors.append(f"compiler.adapter: unknown adapter '{adapter}' (available: {', '.join(sorted(compilers.ADAPTERS))})")
    cfg["compiler"]["adapter"] = adapter
    cfg["compiler"]["executable"] = _clean_string(compiler_raw.get("executable", ""), "compiler.executable", errors)

    if "args_text" in compiler_raw:
        text = _clean_string(compiler_raw["args_text"], "compiler.args", errors, allow_empty=True)
        try:
            args = parse_args_text(text)
        except ConfigError as exc:
            errors.extend(exc.errors)
            args = []
    else:
        args = compiler_raw.get("args", [])
    if not isinstance(args, list):
        errors.append("compiler.args: must be a list of strings")
        args = []
    if len(args) > MAX_ARGS:
        errors.append(f"compiler.args: at most {MAX_ARGS} arguments")
    clean_args = []
    for i, arg in enumerate(args[:MAX_ARGS]):
        # Arguments are kept verbatim (a quoted argument may contain spaces).
        if not isinstance(arg, str) or not arg:
            errors.append(f"compiler.args[{i}]: must be a non-empty string")
        elif len(arg) > MAX_STRING or any(ch in arg for ch in ("\x00", "\n", "\r")):
            errors.append(f"compiler.args[{i}]: too long or contains NUL/line-break characters")
        else:
            clean_args.append(arg)
    cfg["compiler"]["args"] = clean_args
    cfg["compiler"]["timeout_seconds"] = _clean_int(
        compiler_raw.get("timeout_seconds", 60), "compiler.timeout_seconds", TIMEOUT_RANGE, errors)

    for key in PATH_KEYS:
        cfg["paths"][key] = _clean_string(paths_raw.get(key, ""), f"paths.{key}", errors)

    cfg["run"]["default_test_timeout_seconds"] = _clean_int(
        run_raw.get("default_test_timeout_seconds", 5), "run.default_test_timeout_seconds", TIMEOUT_RANGE, errors)
    cfg["run"]["max_output_bytes"] = _clean_int(
        run_raw.get("max_output_bytes", 65536), "run.max_output_bytes", OUTPUT_LIMIT_RANGE, errors)

    if adapter in compilers.ADAPTERS:
        errors.extend(compilers.ADAPTERS[adapter].check_args(clean_args))
    if errors:
        raise ConfigError(errors)
    return cfg


def resolve_in_root(root, value):
    """Resolve ``value`` (relative to ``root`` or absolute) and require it to stay inside ``root``.

    Returns the resolved Path, or None if it escapes the project root.
    """
    root = Path(root).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def resolved_paths(cfg, root=PROJECT_ROOT):
    """Return dict of resolved Paths for a normalised config; raises ConfigError if any escape root."""
    p = cfg["paths"]
    errors = []
    out = {}
    for key in ("source_dir", "build_dir", "tests_file", "report_dir"):
        resolved = resolve_in_root(root, p[key])
        if resolved is None:
            errors.append(f"paths.{key}: '{p[key]}' resolves outside the project directory")
        out[key] = resolved
    if out.get("source_dir") is not None:
        source = resolve_in_root(out["source_dir"], p["source_file"])
        if source is None:
            errors.append(f"paths.source_file: '{p['source_file']}' must be inside the source directory")
        out["source_file"] = source
    if errors:
        raise ConfigError(errors)
    return out


def _check(name, status, message):
    return {"name": name, "status": status, "message": message}


def validate_environment(cfg, root=PROJECT_ROOT):
    """Check a normalised config against the file system without running any command.

    Returns a list of checks: {name, status: ok|warning|error, message}.
    """
    checks = []
    try:
        paths = resolved_paths(cfg, root)
    except ConfigError as exc:
        return [_check("Paths inside project", "error", msg) for msg in exc.errors]
    checks.append(_check("Paths inside project", "ok", f"All paths resolve inside {Path(root).resolve()}"))

    exe = cfg["compiler"]["executable"]
    found = find_executable(exe, root)
    if found:
        checks.append(_check("Compiler executable", "ok", f"'{exe}' found at {found}"))
    else:
        checks.append(_check("Compiler executable", "error",
                             f"Compiler '{exe}' not found on PATH or not executable. "
                             "Install it, or set the full path to the executable."))

    if paths["source_dir"].is_dir():
        checks.append(_check("Source directory", "ok", str(paths["source_dir"])))
    else:
        checks.append(_check("Source directory", "error", f"Directory not found: {paths['source_dir']}"))
    if paths["source_file"].is_file():
        checks.append(_check("Source file", "ok", str(paths["source_file"])))
    else:
        checks.append(_check("Source file", "error", f"File not found: {paths['source_file']}"))

    if paths["tests_file"].is_file():
        try:
            suite = testcases.load_suite(paths["tests_file"])
            enabled = sum(1 for t in suite["tests"] if t["enabled"])
            checks.append(_check("Test cases file", "ok",
                                 f"{len(suite['tests'])} test case(s), {enabled} enabled"))
        except testcases.TestFileError as exc:
            for msg in exc.errors:
                checks.append(_check("Test cases file", "error", msg))
    else:
        checks.append(_check("Test cases file", "error", f"File not found: {paths['tests_file']}"))

    for key, label in (("build_dir", "Build directory"), ("report_dir", "Report directory")):
        target = paths[key]
        if target.is_dir():
            ok = os.access(target, os.W_OK)
            checks.append(_check(label, "ok" if ok else "error",
                                 str(target) if ok else f"Not writable: {target}"))
        elif target.exists():
            checks.append(_check(label, "error", f"Exists but is not a directory: {target}"))
        else:
            checks.append(_check(label, "warning", f"Will be created on first run: {target}"))
    return checks


def find_executable(exe, root=PROJECT_ROOT):
    """Locate a compiler executable by name (on PATH) or by path. Never runs it."""
    if os.sep in exe or (os.altsep and os.altsep in exe):
        path = Path(exe)
        if not path.is_absolute():
            path = Path(root) / path
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    return shutil.which(exe)


def load_config(path=CONFIG_PATH):
    """Load the config file; create it from the example (or built-in defaults) if missing."""
    path = Path(path)
    if not path.exists():
        source = EXAMPLE_CONFIG_PATH if EXAMPLE_CONFIG_PATH.exists() else None
        data = json.loads(source.read_text("utf-8")) if source else default_config()
        save_config(normalize(data), path)
    with path.open("r", encoding="utf-8") as fh:
        return normalize(json.load(fh))


def save_config(cfg, path=CONFIG_PATH):
    """Atomically write a normalised config to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".kit-config-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
