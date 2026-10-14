"""Workflow tests with a fake compiler (no GnuCOBOL needed)."""

import unittest

from app import runner, service, store
from tests.helpers import TempProject, test_case

ECHO_PROGRAM = """\
import sys, time
line = sys.stdin.readline().strip()
if line == "sleep":
    time.sleep(30)
if line == "crash":
    print("boom <b>&amp;</b>", file=sys.stderr)
    sys.exit(2)
print("ECHO=" + line)
"""


class StatusTests(unittest.TestCase):
    def _summary(self, **counts):
        return {"total": sum(counts.values()), "passed": 0, "failed": 0, "errors": 0, "not_run": 0, **counts}

    def test_overall_status_rules(self):
        S = runner.overall_status
        self.assertEqual(S("SUCCESS", self._summary(passed=3)), "PASSED")
        self.assertEqual(S("SUCCESS", self._summary(passed=3, not_run=1)), "PASSED_WITH_SKIPS")
        self.assertEqual(S("SUCCESS", self._summary(passed=3, failed=1)), "FAILED")
        self.assertEqual(S("SUCCESS", self._summary(passed=3, errors=1)), "FAILED")
        self.assertEqual(S("SUCCESS", self._summary(not_run=2)), "NO_TESTS_RUN")
        self.assertEqual(S("SUCCESS", self._summary()), "NO_TESTS_RUN")
        self.assertEqual(S("FAILED", self._summary(not_run=2)), "BUILD_FAILED")
        self.assertEqual(S("ERROR", self._summary(not_run=2)), "BUILD_FAILED")
        self.assertEqual(S("SUCCESS", self._summary(passed=1), setup_ok=False), "ERROR")

    def test_summarize_counts_unknown_as_not_run(self):
        tests = [{"status": "PASS"}, {"status": "FAIL"}, {"status": "ERROR"}, {"status": "NOT RUN"}, {"status": "??"}]
        self.assertEqual(runner.summarize(tests),
                         {"total": 5, "passed": 1, "failed": 1, "errors": 1, "not_run": 2})


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)

    def run_with(self, cfg):
        return runner.execute_run(cfg, root=self.project.root)

    def test_pass_fail_error_and_not_run(self):
        cfg = self.project.fake_config(ECHO_PROGRAM, [
            test_case("PASS-1", "hello", stdout="ECHO=hello", exit_code=0),
            test_case("FAIL-1", "hello", stdout="ECHO=world", exit_code=0),
            test_case("ERR-1", "sleep", stdout="never", timeout_seconds=0.5),
            test_case("CRASH-1", "crash", exit_code=0, compare="exit_code"),
            test_case("SKIP-1", "hello", stdout="ECHO=hello", enabled=False, skip_reason="pending rule"),
        ])
        run = self.run_with(cfg)
        status = {t["id"]: t for t in run["tests"]}
        self.assertEqual(run["build"]["status"], "SUCCESS")
        self.assertEqual(status["PASS-1"]["status"], "PASS")
        self.assertEqual(status["FAIL-1"]["status"], "FAIL")
        self.assertEqual(status["FAIL-1"]["actual"]["stdout"].strip(), "ECHO=hello")
        self.assertEqual(status["ERR-1"]["status"], "ERROR")
        self.assertTrue(status["ERR-1"]["actual"]["timed_out"])
        self.assertEqual(status["CRASH-1"]["status"], "FAIL")
        self.assertEqual(status["CRASH-1"]["actual"]["exit_code"], 2)
        self.assertEqual(status["SKIP-1"]["status"], "NOT RUN")
        self.assertIsNone(status["SKIP-1"]["actual"])
        self.assertIn("pending rule", status["SKIP-1"]["reasons"][0])
        self.assertEqual(run["summary"], {"total": 5, "passed": 1, "failed": 2, "errors": 1, "not_run": 1})
        self.assertEqual(run["status"], "FAILED")

    def test_compilation_failure_runs_no_tests(self):
        cfg = self.project.fake_config("SYNTAX-ERROR\n", [test_case("T1", "x", stdout="x")])
        run = self.run_with(cfg)
        self.assertEqual(run["build"]["status"], "FAILED")
        self.assertEqual(run["build"]["exit_code"], 1)
        self.assertIn("syntax error", run["build"]["stderr"])
        self.assertEqual([t["status"] for t in run["tests"]], ["NOT RUN"])
        self.assertEqual(run["status"], "BUILD_FAILED")

    def test_stale_binary_not_used_after_failed_build(self):
        cfg = self.project.fake_config(ECHO_PROGRAM, [test_case("T1", "x", stdout="ECHO=x")])
        self.assertEqual(self.run_with(cfg)["status"], "PASSED")
        self.project.write("src dir/prog.py", "SYNTAX-ERROR")
        run = self.run_with(cfg)
        self.assertEqual(run["status"], "BUILD_FAILED")
        self.assertFalse((self.project.root / "build out" / "prog").exists())

    def test_missing_compiler(self):
        cfg = self.project.fake_config(ECHO_PROGRAM, [test_case("T1", "x", stdout="ECHO=x")])
        cfg["compiler"]["executable"] = "no-such-compiler-xyz"
        run = self.run_with(cfg)
        self.assertEqual(run["build"]["status"], "ERROR")
        self.assertIn("not found", run["build"]["error"])
        self.assertEqual(run["tests"][0]["status"], "NOT RUN")
        self.assertEqual(run["summary"]["passed"], 0)
        self.assertEqual(run["status"], "BUILD_FAILED")

    def test_compile_timeout(self):
        cfg = self.project.fake_config(ECHO_PROGRAM, [test_case("T1", "x", stdout="ECHO=x")])
        self.project.write("tools/fake_cc.py", "import time; time.sleep(30)")
        cfg["compiler"]["timeout_seconds"] = 1
        run = self.run_with(cfg)
        self.assertEqual(run["build"]["status"], "ERROR")
        self.assertTrue(run["build"]["timed_out"])
        self.assertEqual(run["status"], "BUILD_FAILED")

    def test_setup_error_executes_nothing(self):
        cfg = self.project.fake_config(ECHO_PROGRAM, [test_case("T1", "x", stdout="ECHO=x")])
        cfg["paths"]["source_file"] = "missing.py"
        run = self.run_with(cfg)
        self.assertEqual(run["status"], "ERROR")
        self.assertEqual(run["build"]["status"], "NOT RUN")
        self.assertIsNone(run["build"]["command"])

    def test_run_and_record_writes_report_and_record(self):
        cfg = self.project.fake_config(ECHO_PROGRAM, [test_case("T1", "x", stdout="ECHO=x")])
        runs_dir = self.project.root / "runs"
        run = service.run_and_record(cfg, root=self.project.root, runs_dir=runs_dir)
        self.assertEqual(store.load_run(run["run_id"], runs_dir)["status"], "PASSED")
        self.assertEqual(service.report_path_for(run, self.project.root).parent,
                         self.project.root / "report out")
        self.assertEqual(store.list_runs(runs_dir)[0]["run_id"], run["run_id"])

    def test_store_rejects_bad_run_ids(self):
        for bad in ("../../etc/passwd", "x", "", None):
            self.assertIsNone(store.load_run(bad, self.project.root))


if __name__ == "__main__":
    unittest.main()
