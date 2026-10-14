---
name: cobol-test-workflow
description: Inspect, test and report on the COBOL program configured in this repository's COBOL Test Automation Kit. Use when asked to explain the COBOL program, propose or review test cases, run the build/tests, diagnose failures, or refresh the HTML test report.
---

# COBOL test workflow

The scripts in this repository do the deterministic work (validation, compilation,
execution, comparison, reporting). Your job is to coordinate them, read their real
output, and explain it. You cannot guarantee that a COBOL program is correct; every
business rule and every code change needs review by a human developer.

## Commands you may run

Run from the repository root. Do not run other build or execution commands for the
program under test, and never run the compiled program outside the test runner.

| Purpose | Command |
|---|---|
| Validate config (runs nothing) | `python3 -m app validate` |
| Build + run all tests, write report | `python3 -m app run` |
| Kit's own unit/integration tests | `python3 -m unittest discover -s tests -t .` |

Results are stored in `runs/<run_id>.json`; the report path is printed by `run`.

## Workflow

1. **Inspect the configuration and source.** Read `config/kit.config.json` (create it
   with `python3 -m app validate` if missing), the source file it points to, and the
   test file. Run `python3 -m app validate` and report any errors.
2. **Explain the program.** Describe inputs, outputs, exit codes and calculations as
   the code implements them. List every assumption and every place where the code is
   ambiguous.
3. **Propose test cases.** Use the JSON format in `app/testcases.py` (normal, boundary,
   invalid, regression). Label each case either **confirmed** (the user stated the
   rule) or **inferred** (you derived it from the code). An expected value inferred
   from the code only proves the code does what it does; say so. Add cases to the
   test file only after the user agrees.
4. **Run** `python3 -m app run`.
5. **Review real output.** Read the run record in `runs/<run_id>.json` (build
   stdout/stderr, each test's actual stdout, stderr, exit code, reasons). Quote the
   evidence; never describe a result you did not read.
6. **Diagnose failures** without masking them:
   - Never change an expected value to make a test pass unless the user confirms
     the expectation was wrong; then record why in the test description.
   - Never disable a test, loosen a comparison mode, or raise a timeout to hide a
     failure.
   - Never edit the COBOL source automatically. Propose a fix as a diff with the
     reasoning and let the developer apply or approve it.
   - Distinguish build failures, test failures (FAIL), execution errors (ERROR:
     timeout, crash) and tests not run (NOT RUN).
7. **Refresh the report** by running `python3 -m app run` again after any approved
   change. Reports are only generated from recorded runs; do not write or edit
   report HTML by hand.
8. **Summarize for the developer:** what changed (files and why), run ID, overall
   status, counts (passed/failed/errors/not run), remaining failures with evidence,
   inferred vs confirmed rules, and what still needs human review.

## Rules

- A test that did not execute is NOT RUN, never PASS. If something could not be run
  in this environment (e.g. compiler missing), say exactly that and give the command
  to run elsewhere.
- Use synthetic data only. Do not add credentials, employer/client code or
  proprietary configuration to this repository.
- Do not install packages or change machine configuration without asking.
