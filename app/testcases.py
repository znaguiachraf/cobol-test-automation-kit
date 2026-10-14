"""Test-case file loading and output comparison rules.

Test file format (JSON)::

    {
      "suite": "name",
      "default_timeout_seconds": 5,          # optional
      "tests": [
        {
          "id": "TC-001",                    # unique, required
          "description": "text",             # required
          "category": "normal",              # optional free text
          "input": "35,20000,0",             # sent to the program's stdin (newline appended)
          "expected": {"stdout": "...", "exit_code": 0},
          "compare": "exact",                # exact | contains | regex | exit_code
          "timeout_seconds": 5,              # optional
          "enabled": true,                   # optional, false -> NOT RUN
          "skip_reason": "text"              # optional
        }
      ]
    }
"""

import json
import re
from pathlib import Path

COMPARE_MODES = ("exact", "contains", "regex", "exit_code")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
MAX_INPUT = 64 * 1024


class TestFileError(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def load_suite(path):
    """Load and validate a test file. Raises TestFileError with every problem found."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise TestFileError([f"{path.name}: cannot read file ({exc})"])
    except json.JSONDecodeError as exc:
        raise TestFileError([f"{path.name}: invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"])
    return validate_suite(raw, path.name)


def validate_suite(raw, label="tests"):
    errors = []
    if not isinstance(raw, dict) or not isinstance(raw.get("tests"), list):
        raise TestFileError([f"{label}: must be an object with a 'tests' list"])
    default_timeout = raw.get("default_timeout_seconds")
    if default_timeout is not None and not _valid_timeout(default_timeout):
        errors.append(f"{label}: default_timeout_seconds must be a number between 0.1 and 3600")
        default_timeout = None

    tests, seen = [], set()
    for index, item in enumerate(raw["tests"]):
        where = f"{label}: test #{index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        test_id = item.get("id")
        if not isinstance(test_id, str) or not ID_PATTERN.match(test_id):
            errors.append(f"{where}: 'id' must be 1-40 characters of letters, digits, '_', '-' or '.'")
            continue
        where = f"{label}: {test_id}"
        if test_id in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(test_id)

        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{where}: 'description' is required")
        test_input = item.get("input", "")
        if not isinstance(test_input, str) or len(test_input) > MAX_INPUT:
            errors.append(f"{where}: 'input' must be a string up to {MAX_INPUT} characters")
        compare = item.get("compare", "exact")
        if compare not in COMPARE_MODES:
            errors.append(f"{where}: 'compare' must be one of {', '.join(COMPARE_MODES)}")
        expected = item.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{where}: 'expected' must be an object")
            expected = {}
        exp_stdout = expected.get("stdout")
        exp_code = expected.get("exit_code")
        if exp_stdout is not None and not isinstance(exp_stdout, str):
            errors.append(f"{where}: expected.stdout must be a string")
        if exp_code is not None and (isinstance(exp_code, bool) or not isinstance(exp_code, int)):
            errors.append(f"{where}: expected.exit_code must be an integer")
        if compare == "exit_code" and exp_code is None:
            errors.append(f"{where}: compare 'exit_code' needs expected.exit_code")
        if compare in ("exact", "contains", "regex") and exp_stdout is None:
            errors.append(f"{where}: compare '{compare}' needs expected.stdout")
        if compare == "regex" and isinstance(exp_stdout, str):
            try:
                re.compile(exp_stdout)
            except re.error as exc:
                errors.append(f"{where}: invalid regex ({exc})")
        timeout = item.get("timeout_seconds", default_timeout)
        if timeout is not None and not _valid_timeout(timeout):
            errors.append(f"{where}: timeout_seconds must be a number between 0.1 and 3600")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{where}: 'enabled' must be true or false")

        tests.append({
            "id": test_id,
            "description": description if isinstance(description, str) else "",
            "category": str(item.get("category", "")),
            "input": test_input if isinstance(test_input, str) else "",
            "expected": {"stdout": exp_stdout, "exit_code": exp_code},
            "compare": compare,
            "timeout_seconds": timeout,
            "enabled": enabled is not False,
            "skip_reason": str(item.get("skip_reason", "")),
        })
    if errors:
        raise TestFileError(errors)
    return {"suite": str(raw.get("suite", label)), "tests": tests}


def _valid_timeout(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0.1 <= value <= 3600


def normalize_output(text):
    """Normalise program output for comparison: unify line endings, strip trailing
    whitespace on every line (COBOL DISPLAY pads fields) and trailing blank lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def compare(test, stdout, exit_code):
    """Compare actual output with a test's expectations.

    Returns (passed: bool, reasons: list[str]). Rules:
      exact     normalised stdout == expected.stdout (normalised the same way)
      contains  expected.stdout is a substring of normalised stdout
      regex     re.search(expected.stdout, normalised stdout, MULTILINE) matches
      exit_code only the exit code is checked
    If expected.exit_code is set it is checked for every mode.
    """
    reasons = []
    expected = test["expected"]
    actual = normalize_output(stdout)
    mode = test["compare"]
    exp_stdout = expected.get("stdout")
    if mode == "exact" and actual != normalize_output(exp_stdout):
        reasons.append("stdout differs from expected (exact match)")
    elif mode == "contains" and exp_stdout not in actual:
        reasons.append("stdout does not contain the expected text")
    elif mode == "regex" and not re.search(exp_stdout, actual, re.MULTILINE):
        reasons.append("stdout does not match the expected regular expression")
    exp_code = expected.get("exit_code")
    if exp_code is not None and exit_code != exp_code:
        reasons.append(f"exit code {exit_code} != expected {exp_code}")
    return (not reasons, reasons)
