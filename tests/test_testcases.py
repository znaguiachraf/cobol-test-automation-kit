import unittest

from app import testcases
from tests.helpers import test_case


def suite(*tests):
    return testcases.validate_suite({"tests": list(tests)})["tests"]


class CompareTests(unittest.TestCase):
    def test_exact_ignores_trailing_spaces_and_line_endings(self):
        [t] = suite(test_case("A", "", stdout="RESULT=OK\nLINE 2", exit_code=0))
        self.assertEqual(testcases.compare(t, "RESULT=OK   \r\nLINE 2    \n\n", 0), (True, []))

    def test_exact_mismatch_fails(self):
        [t] = suite(test_case("A", "", stdout="RESULT=OK PREMIUM=700.00"))
        ok, reasons = testcases.compare(t, "RESULT=OK PREMIUM=700.01", 0)
        self.assertFalse(ok)
        self.assertIn("exact", reasons[0])

    def test_exit_code_checked_in_every_mode(self):
        [t] = suite(test_case("A", "", stdout="E03", exit_code=4, compare="contains"))
        ok, reasons = testcases.compare(t, "RESULT=ERROR CODE=E03", 0)
        self.assertFalse(ok)
        self.assertEqual(reasons, ["exit code 0 != expected 4"])
        self.assertTrue(testcases.compare(t, "RESULT=ERROR CODE=E03", 4)[0])

    def test_none_exit_code_never_matches(self):
        [t] = suite(test_case("A", "", exit_code=0, compare="exit_code"))
        self.assertFalse(testcases.compare(t, "", None)[0])

    def test_regex(self):
        [t] = suite(test_case("A", "", stdout=r"^RESULT=OK PREMIUM=\d+\.\d{2}$", compare="regex"))
        self.assertTrue(testcases.compare(t, "RESULT=OK PREMIUM=12.50\n", 0)[0])
        self.assertFalse(testcases.compare(t, "RESULT=OK PREMIUM=12.5\n", 0)[0])


class SuiteValidationTests(unittest.TestCase):
    def test_defaults(self):
        [t] = suite(test_case("A", "1", stdout="x"))
        self.assertTrue(t["enabled"])
        self.assertIsNone(t["timeout_seconds"])

    def test_default_timeout_inherited(self):
        tests = testcases.validate_suite({"default_timeout_seconds": 2, "tests": [test_case("A", "", stdout="x")]})
        self.assertEqual(tests["tests"][0]["timeout_seconds"], 2)

    def test_collects_all_errors(self):
        with self.assertRaises(testcases.TestFileError) as ctx:
            suite(
                test_case("A", "", stdout="x"),
                test_case("A", "", stdout="x"),                     # duplicate
                test_case("bad id!", "", stdout="x"),               # invalid id
                test_case("B", "", compare="exact"),                # no expected stdout
                test_case("C", "", stdout="(", compare="regex"),    # bad regex
                test_case("D", "", stdout="x", compare="fuzzy"),    # unknown mode
                test_case("E", "", stdout="x", timeout_seconds=0),  # bad timeout
            )
        text = " | ".join(ctx.exception.errors)
        for fragment in ("duplicate id", "'id' must be", "needs expected.stdout", "invalid regex",
                         "'compare' must be", "timeout_seconds"):
            self.assertIn(fragment, text)

    def test_not_an_object(self):
        with self.assertRaises(testcases.TestFileError):
            testcases.validate_suite([])

    def test_sample_suite_is_valid(self):
        from tests.helpers import REPO
        loaded = testcases.load_suite(REPO / "samples/tests/premcalc_tests.json")
        categories = {t["category"] for t in loaded["tests"]}
        self.assertTrue({"normal", "boundary", "invalid", "regression"} <= categories)
        self.assertTrue(any(not t["enabled"] for t in loaded["tests"]))


if __name__ == "__main__":
    unittest.main()
