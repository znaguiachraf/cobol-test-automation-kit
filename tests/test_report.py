import unittest

from app import report, runner
from tests.helpers import TempProject, test_case

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>&'


def fake_run(root):
    tests = [
        {"id": "T1", "description": EVIL, "category": "normal", "input": EVIL,
         "expected": {"stdout": EVIL, "exit_code": 0}, "compare": "exact", "timeout_seconds": 5,
         "status": "FAIL", "actual": {"stdout": EVIL, "stderr": EVIL, "exit_code": 1},
         "duration_ms": 3, "reasons": [EVIL]},
        {"id": "T2", "description": "skipped", "category": "", "input": "", "expected": {"exit_code": 0},
         "compare": "exit_code", "timeout_seconds": 5, "status": "NOT RUN", "actual": None,
         "duration_ms": None, "reasons": ["Disabled in test file"]},
    ]
    summary = runner.summarize(tests)
    return {
        "run_id": "20260101-000000-abcd", "tool": {"version": "test"}, "project_name": EVIL,
        "started_at": "s", "ended_at": "e", "suite": EVIL,
        "environment": {"platform": "p", "python": "3", "compiler_version": EVIL},
        "config": {"compiler": {"adapter": "gnucobol", "executable": "cobc", "args": [EVIL]},
                   "paths": {"source_dir": str(root / "src"), "source_file": "A.cbl"}, "run": {}},
        "checks": [{"name": "x", "status": "error", "message": EVIL}],
        "build": {"status": "SUCCESS", "command": ["cobc", str(root / "src/A.cbl")], "exit_code": 0,
                  "stdout": EVIL, "stderr": f"{root}/src/A.cbl: warning {EVIL}", "duration_ms": 1, "error": None},
        "tests": tests, "summary": summary, "status": runner.overall_status("SUCCESS", summary), "notes": [EVIL],
    }


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)

    def test_untrusted_strings_are_escaped(self):
        html = report.render_report(fake_run(self.project.root), root=self.project.root)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", html)

    def test_counts_statuses_and_limitations(self):
        html = report.render_report(fake_run(self.project.root), root=self.project.root)
        self.assertIn("FAILED", html)
        self.assertIn("NOT RUN", html)
        self.assertIn("T2</code> not run", html)
        self.assertIn("Failures and diagnostics", html)
        self.assertNotIn("SAMPLE REPORT", html)

    def test_local_paths_are_sanitized(self):
        html = report.render_report(fake_run(self.project.root), root=self.project.root)
        self.assertNotIn(str(self.project.root), html)
        self.assertIn("&lt;project&gt;/src/A.cbl", html)

    def test_sample_label_and_no_external_resources(self):
        html = report.render_report(fake_run(self.project.root), sample=True, root=self.project.root)
        self.assertIn("SAMPLE REPORT", html)
        for marker in ("http://", "https://", "<link", "<script"):
            self.assertNotIn(marker, html)

    def test_report_from_real_run(self):
        cfg = self.project.fake_config('print("A<B & C>D")', [test_case("T1", "", stdout="A<B & C>D")])
        run = runner.execute_run(cfg, root=self.project.root)
        self.assertEqual(run["status"], "PASSED")
        path = report.write_report(run, self.project.root / "report out", root=self.project.root)
        html = path.read_text()
        self.assertEqual(path.name, f"report-{run['run_id']}.html")
        self.assertIn("A&lt;B &amp; C&gt;D", html)
        self.assertNotIn("A<B", html)


if __name__ == "__main__":
    unittest.main()
