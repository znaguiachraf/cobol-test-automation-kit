"""Test helpers: temporary projects (with spaces in their path) and a fake compiler."""

import json
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

from app import config as config_mod

REPO = Path(__file__).resolve().parent.parent

# A stand-in "compiler" used through the generic adapter. It "compiles" a Python
# source file into an executable script, or fails if the source contains
# SYNTAX-ERROR. This exercises the whole workflow without needing GnuCOBOL.
FAKE_COMPILER = textwrap.dedent(f"""\
    import os, sys
    source, output = sys.argv[1], sys.argv[2]
    text = open(source, encoding="utf-8").read()
    if "SYNTAX-ERROR" in text:
        print(f"{{source}}:1: error: syntax error <unexpected>", file=sys.stderr)
        sys.exit(1)
    with open(output, "w", encoding="utf-8") as fh:
        fh.write("#!{sys.executable}\\n" + text)
    os.chmod(output, 0o755)
    print("fake compile ok")
""")


class TempProject:
    """A throwaway project root containing a space in its path."""

    def __init__(self):
        self.base = Path(tempfile.mkdtemp(prefix="cobol kit "))
        self.root = (self.base / "my project").resolve()
        (self.root / "src dir").mkdir(parents=True)
        (self.root / "tests").mkdir()

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_tests(self, tests, rel="tests/cases.json", **extra):
        return self.write(rel, json.dumps({"suite": "temp suite", "tests": tests, **extra}))

    def fake_config(self, program_source, tests, **overrides):
        """Config using the fake compiler (generic adapter) and the given program/tests."""
        self.write("tools/fake_cc.py", FAKE_COMPILER)
        self.write("src dir/prog.py", program_source)
        self.write_tests(tests)
        cfg = config_mod.default_config()
        cfg["compiler"].update(adapter="generic", executable=sys.executable,
                               args=[str(self.root / "tools/fake_cc.py"), "{source}", "{output}"],
                               timeout_seconds=30)
        cfg["paths"].update(source_dir="src dir", source_file="prog.py", build_dir="build out",
                            tests_file="tests/cases.json", report_dir="report out")
        cfg["run"]["default_test_timeout_seconds"] = 5
        for key, value in overrides.items():
            cfg[key].update(value)
        return config_mod.normalize(cfg)


def test_case(id_, input_, stdout=None, exit_code=None, compare="exact", **extra):
    expected = {}
    if stdout is not None:
        expected["stdout"] = stdout
    if exit_code is not None:
        expected["exit_code"] = exit_code
    return {"id": id_, "description": f"case {id_}", "input": input_, "expected": expected,
            "compare": compare, **extra}
