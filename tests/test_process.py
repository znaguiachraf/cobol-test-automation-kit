import sys
import time
import unittest

from app.process import TRUNCATION_NOTE, run_process

PY = sys.executable


class RunProcessTests(unittest.TestCase):
    def test_captures_stdout_stderr_exit_code_and_stdin(self):
        code = "import sys; data=sys.stdin.read(); print('got', data.strip()); print('warn', file=sys.stderr); sys.exit(3)"
        r = run_process([PY, "-c", code], stdin_text="hello\n", timeout=10)
        self.assertEqual(r["exit_code"], 3)
        self.assertEqual(r["stdout"].strip(), "got hello")
        self.assertEqual(r["stderr"].strip(), "warn")
        self.assertIsNone(r["error"])
        self.assertFalse(r["timed_out"])
        self.assertTrue(r["started_at"] and r["ended_at"])

    def test_arguments_are_not_interpreted_by_a_shell(self):
        r = run_process([PY, "-c", "import sys; print(sys.argv[1])", "$(echo injected); ls *"], timeout=10)
        self.assertEqual(r["stdout"].strip(), "$(echo injected); ls *")

    def test_timeout_kills_process(self):
        start = time.monotonic()
        r = run_process([PY, "-c", "import time; time.sleep(30)"], timeout=0.5)
        self.assertLess(time.monotonic() - start, 10)
        self.assertTrue(r["timed_out"])
        self.assertIsNone(r["exit_code"])
        self.assertIn("Timed out", r["error"])

    def test_timeout_kills_child_processes(self):
        # The child spawns a grandchild that keeps stdout open; killing the group must not hang.
        code = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); time.sleep(30)"
        start = time.monotonic()
        r = run_process([PY, "-c", code], timeout=0.5)
        self.assertTrue(r["timed_out"])
        self.assertLess(time.monotonic() - start, 10)

    def test_missing_executable(self):
        r = run_process(["/nonexistent/compiler-xyz", "--version"], timeout=5)
        self.assertIsNone(r["exit_code"])
        self.assertIn("not found", r["error"])

    def test_output_truncated(self):
        r = run_process([PY, "-c", "print('x' * 5000)"], timeout=10, max_output_bytes=1024)
        self.assertTrue(r["truncated"])
        self.assertTrue(r["stdout"].endswith(TRUNCATION_NOTE))
        self.assertEqual(len(r["stdout"]), 1024 + len(TRUNCATION_NOTE))

    def test_program_that_ignores_stdin(self):
        r = run_process([PY, "-c", "print('ok')"], stdin_text="x" * 1_000_000, timeout=10)
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["stdout"].strip(), "ok")

    def test_rejects_string_command(self):
        with self.assertRaises(TypeError):
            run_process("echo hi")


if __name__ == "__main__":
    unittest.main()
