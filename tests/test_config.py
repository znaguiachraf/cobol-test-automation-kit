import json
import unittest

from app import config as config_mod
from tests.helpers import TempProject, test_case


class NormalizeTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        cfg = config_mod.normalize(config_mod.default_config())
        self.assertEqual(cfg["compiler"]["args"], ["-x", "-free", "-Wall"])

    def test_args_text_is_split_safely(self):
        raw = config_mod.default_config()
        raw["compiler"].pop("args")
        raw["compiler"]["args_text"] = "-x -free -I 'copy books' \"-DNAME=a b\" $(rm -rf /) ;ls"
        cfg = config_mod.normalize(raw)
        self.assertEqual(cfg["compiler"]["args"],
                         ["-x", "-free", "-I", "copy books", "-DNAME=a b", "$(rm", "-rf", "/)", ";ls"])

    def test_unbalanced_quotes_rejected(self):
        raw = config_mod.default_config()
        raw["compiler"]["args_text"] = "-x 'oops"
        with self.assertRaises(config_mod.ConfigError) as ctx:
            config_mod.normalize(raw)
        self.assertIn("cannot parse flags", ctx.exception.errors[0])

    def test_gnucobol_rejects_output_flag(self):
        raw = config_mod.default_config()
        raw["compiler"]["args"] = ["-x", "-o", "/tmp/elsewhere"]
        with self.assertRaises(config_mod.ConfigError):
            config_mod.normalize(raw)

    def test_generic_adapter_needs_source_placeholder(self):
        raw = config_mod.default_config()
        raw["compiler"].update(adapter="generic", args=["-x"])
        with self.assertRaises(config_mod.ConfigError) as ctx:
            config_mod.normalize(raw)
        self.assertIn("{source}", ctx.exception.errors[0])

    def test_rejects_bad_values(self):
        raw = config_mod.default_config()
        raw["compiler"]["adapter"] = "nope"
        raw["compiler"]["executable"] = "cobc\nrm"
        raw["compiler"]["timeout_seconds"] = 0
        raw["paths"]["source_dir"] = ""
        raw["run"]["max_output_bytes"] = "lots"
        with self.assertRaises(config_mod.ConfigError) as ctx:
            config_mod.normalize(raw)
        text = " | ".join(ctx.exception.errors)
        for field in ("compiler.adapter", "compiler.executable", "compiler.timeout_seconds",
                      "paths.source_dir", "run.max_output_bytes"):
            self.assertIn(field, text)

    def test_rejects_non_object(self):
        with self.assertRaises(config_mod.ConfigError):
            config_mod.normalize(["not", "an", "object"])


class EnvironmentValidationTests(unittest.TestCase):
    def setUp(self):
        self.project = TempProject()
        self.addCleanup(self.project.cleanup)

    def _checks(self, cfg):
        return {c["name"]: c for c in config_mod.validate_environment(cfg, self.project.root)}

    def test_valid_project_with_spaces_in_paths(self):
        cfg = self.project.fake_config("print('x')", [test_case("T1", "", stdout="x")])
        checks = self._checks(cfg)
        self.assertNotIn("error", [c["status"] for c in checks.values()], checks)
        self.assertIn("my project", checks["Source file"]["message"])
        self.assertEqual(checks["Build directory"]["status"], "warning")  # created on first run

    def test_missing_compiler_reported(self):
        cfg = self.project.fake_config("print('x')", [test_case("T1", "", stdout="x")])
        cfg["compiler"]["executable"] = "definitely-not-a-compiler-xyz"
        check = self._checks(cfg)["Compiler executable"]
        self.assertEqual(check["status"], "error")
        self.assertIn("not found", check["message"])

    def test_paths_outside_project_rejected(self):
        cfg = self.project.fake_config("print('x')", [test_case("T1", "", stdout="x")])
        cfg["paths"]["build_dir"] = "../escape"
        cfg["paths"]["source_file"] = "../../etc/passwd"
        checks = config_mod.validate_environment(cfg, self.project.root)
        self.assertTrue(all(c["status"] == "error" for c in checks))
        self.assertTrue(any("build_dir" in c["message"] for c in checks))
        self.assertTrue(any("source_file" in c["message"] for c in checks))

    def test_missing_files_and_invalid_test_file(self):
        cfg = self.project.fake_config("print('x')", [test_case("T1", "", stdout="x")])
        cfg["paths"]["source_file"] = "missing.cbl"
        self.project.write("tests/cases.json", "{ not json")
        checks = self._checks(cfg)
        self.assertEqual(checks["Source file"]["status"], "error")
        self.assertEqual(checks["Test cases file"]["status"], "error")
        self.assertIn("invalid JSON", checks["Test cases file"]["message"])

    def test_save_and_load_roundtrip(self):
        path = self.project.root / "config" / "kit.config.json"
        cfg = config_mod.default_config()
        cfg["compiler"]["args"] = ["-x", "-I", "dir with space"]
        config_mod.save_config(config_mod.normalize(cfg), path)
        self.assertEqual(config_mod.load_config(path), cfg)
        self.assertEqual(json.loads(path.read_text())["compiler"]["args"][2], "dir with space")


if __name__ == "__main__":
    unittest.main()
