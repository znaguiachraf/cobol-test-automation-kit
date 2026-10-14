"""Integration tests with real GnuCOBOL. Skipped (and reported as skipped) if cobc is not installed."""

import shutil
import unittest

from app import config as config_mod, runner
from tests.helpers import REPO, TempProject, test_case

HAVE_COBC = shutil.which("cobc") is not None

BROKEN = """IDENTIFICATION DIVISION.
PROGRAM-ID. BROKEN.
PROCEDURE DIVISION.
    DISPLAY "missing period and bad verb"
    MOVEX 1 TO NOTHING
    STOP RUN.
"""

LOOP = """IDENTIFICATION DIVISION.
PROGRAM-ID. LOOPER.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-N PIC 9 VALUE 0.
PROCEDURE DIVISION.
    PERFORM UNTIL WS-N = 1
        CONTINUE
    END-PERFORM
    STOP RUN.
"""


@unittest.skipUnless(HAVE_COBC, "GnuCOBOL (cobc) is not installed")
class GnuCobolTests(unittest.TestCase):
    def setUp(self):
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)

    def cobc_config(self, source_name, source_text, tests):
        self.project.write(f"src dir/{source_name}", source_text)
        self.project.write_tests(tests)
        cfg = config_mod.default_config()
        cfg["paths"].update(source_dir="src dir", source_file=source_name, build_dir="build out",
                            tests_file="tests/cases.json", report_dir="report out")
        return config_mod.normalize(cfg)

    def test_sample_program_passes_in_path_with_spaces(self):
        source = (REPO / "samples/src/PREMCALC.cbl").read_text()
        cfg = self.cobc_config("PREMCALC.cbl", source, [
            test_case("OK", "35,20000,0", stdout="RESULT=OK PREMIUM=700.00", exit_code=0),
            test_case("INV", "17,20000,0", stdout="CODE=E03", exit_code=4, compare="contains"),
        ])
        run = runner.execute_run(cfg, root=self.project.root)
        self.assertEqual(run["build"]["status"], "SUCCESS", run["build"]["stderr"])
        self.assertIn("my project", run["build"]["output_file"])
        self.assertEqual(run["status"], "PASSED", [t["reasons"] for t in run["tests"]])
        self.assertIn("GnuCOBOL", run["environment"]["compiler_version"])

    def test_wrong_expectation_stays_failed(self):
        source = (REPO / "samples/src/PREMCALC.cbl").read_text()
        cfg = self.cobc_config("PREMCALC.cbl", source, [
            test_case("WRONG", "35,20000,0", stdout="RESULT=OK PREMIUM=999.99", exit_code=0),
        ])
        run = runner.execute_run(cfg, root=self.project.root)
        self.assertEqual(run["tests"][0]["status"], "FAIL")
        self.assertEqual(run["tests"][0]["actual"]["stdout"].strip(), "RESULT=OK PREMIUM=700.00")
        self.assertEqual(run["status"], "FAILED")

    def test_compilation_failure(self):
        cfg = self.cobc_config("BROKEN.cbl", BROKEN, [test_case("T1", "", exit_code=0, compare="exit_code")])
        run = runner.execute_run(cfg, root=self.project.root)
        self.assertEqual(run["build"]["status"], "FAILED")
        self.assertNotEqual(run["build"]["exit_code"], 0)
        self.assertTrue(run["build"]["stderr"].strip())
        self.assertEqual(run["tests"][0]["status"], "NOT RUN")
        self.assertEqual(run["status"], "BUILD_FAILED")

    def test_program_timeout(self):
        cfg = self.cobc_config("LOOPER.cbl", LOOP, [
            test_case("HANG", "", exit_code=0, compare="exit_code", timeout_seconds=1),
        ])
        run = runner.execute_run(cfg, root=self.project.root)
        self.assertEqual(run["build"]["status"], "SUCCESS", run["build"]["stderr"])
        self.assertEqual(run["tests"][0]["status"], "ERROR")
        self.assertTrue(run["tests"][0]["actual"]["timed_out"])

    def test_generic_adapter_with_cobc(self):
        """Switching compiler/adapter needs only config changes."""
        source = (REPO / "samples/src/PREMCALC.cbl").read_text()
        cfg = self.cobc_config("PREMCALC.cbl", source,
                               [test_case("OK", "25,20000,0", stdout="RESULT=OK PREMIUM=700.00")])
        cfg["compiler"].update(adapter="generic", args=["-x", "-free", "-o", "{output}", "{source}"])
        run = runner.execute_run(config_mod.normalize(cfg), root=self.project.root)
        self.assertEqual(run["status"], "PASSED")


if __name__ == "__main__":
    unittest.main()
