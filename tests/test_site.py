import json
import os
import unittest
from pathlib import Path

from app import __main__ as cli, site
from tests.helpers import TempProject, test_case
from tests.test_report import EVIL, fake_run


class SiteExportTests(unittest.TestCase):
    def setUp(self):
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)
        self.root = self.project.root
        self.cfg = self.project.fake_config(
            f"print({EVIL!r})\n", [test_case("T1", EVIL, stdout=EVIL, description=EVIL)])
        self.cfg["project_name"] = EVIL
        self.out = self.root / "site"

    def runs(self, *ids):
        out = []
        for run_id in ids:
            run = fake_run(self.root)
            run["run_id"] = run_id
            out.append(run)
        return out

    def export(self, runs):
        site.export_site(runs, self.cfg, self.out, root=self.root)
        return {p.relative_to(self.out).as_posix(): p.read_text("utf-8")
                for p in self.out.rglob("*") if p.is_file()}

    def test_writes_all_pages(self):
        files = self.export(self.runs("20260102-000000-bbbb", "20260101-000000-aaaa"))
        for name in ("index.html", "tests.html", "source.html", ".htaccess", "data/index.json",
                     "reports/report-20260102-000000-bbbb.html", "reports/report-20260101-000000-aaaa.html",
                     "data/runs/20260101-000000-aaaa.json"):
            self.assertIn(name, files)
        self.assertIn("Content-Security-Policy", files[".htaccess"])
        self.assertIn("Options -Indexes", files[".htaccess"])
        self.assertIn("href='reports/report-20260101-000000-aaaa.html'", files["index.html"])

    def test_untrusted_strings_are_escaped_everywhere(self):
        files = self.export(self.runs("20260101-000000-aaaa"))
        for name, text in files.items():
            if name.endswith(".html"):
                self.assertNotIn("<script", text, name)
                self.assertNotIn("<img", text, name)
        self.assertIn("&lt;script&gt;", files["tests.html"])
        self.assertIn("&lt;script&gt;", files["source.html"])

    def test_local_paths_are_not_published(self):
        files = self.export(self.runs("20260101-000000-aaaa"))
        home = os.path.expanduser("~")
        for name, text in files.items():
            self.assertNotIn(str(self.root), text, name)
            self.assertNotIn(home + os.sep, text, name)
        record = json.loads(files["data/runs/20260101-000000-aaaa.json"])
        self.assertIn("<project>", record["build"]["stderr"])

    def test_history_is_newest_first_and_capped(self):
        ids = [f"2026{m:02d}{d:02d}-000000-abcd" for m in range(1, 4) for d in range(1, 28)]
        runs = self.runs(*sorted(ids, reverse=True))
        files = self.export(runs)
        index = json.loads(files["data/index.json"])["runs"]
        self.assertEqual(len(index), site.MAX_RUNS)
        self.assertEqual(index[0], max(ids))
        html = files["index.html"]
        self.assertLess(html.index(index[0]), html.index(index[1]))
        self.assertIn(f"History ({site.MAX_RUNS} runs)", html)

    def test_empty_history(self):
        files = self.export([])
        self.assertIn("No runs have been published yet", files["index.html"])
        self.assertEqual(json.loads(files["data/index.json"]), {"runs": []})

    def test_cli_rejects_out_outside_project(self):
        for bad in ("../outside", "/tmp/elsewhere", "."):
            self.assertEqual(cli.main(["export", "--out", bad]), 1)
        self.assertFalse(Path("/tmp/elsewhere/index.html").exists())


if __name__ == "__main__":
    unittest.main()
