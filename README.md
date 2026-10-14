# COBOL Test Automation Kit

![tests](../../actions/workflows/tests.yml/badge.svg)

A local web tool for COBOL testing: configure the compiler in the browser, build and run
test cases with one click, inspect real results and logs, and generate a standalone HTML
test report.

- **Configure**: compiler executable, flags, source/build/test/report paths, timeouts
- **Execute**: safe build + test workflow (argument lists, timeouts, no shell)
- **Report**: Results page with history, plus a printable, offline HTML report

Built with the Python 3 standard library and vanilla HTML/CSS/JS. It has no dependencies
and needs no network access. The bundled sample (`PREMCALC`) and its data are **synthetic**.

> Screenshots: _add `docs/screenshot-config.png`, `docs/screenshot-results.png` and a short demo GIF here._
> **New here?** Open the step-by-step [Getting Started guide](docs/getting-started.html) in your browser.
>
> See [`docs/sample-report.html`](docs/sample-report.html) for a sample report (clearly labelled SAMPLE).

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3 | Standard library only. Tested only with Python 3.13. |
| GnuCOBOL (`cobc`) | Optional for starting the app, required to compile the sample. Developed with GnuCOBOL 3.2. |

Install GnuCOBOL: Debian/Ubuntu `sudo apt install gnucobol`, Fedora `sudo dnf install gnucobol`,
macOS `brew install gnucobol`. Without it, the app still starts and reports
"compiler not found". It never pretends a build or test succeeded.

## Start

```bash
python3 -m app
```

- Configuration page: <http://127.0.0.1:8765/config>
- Results page: <http://127.0.0.1:8765/results>

Use another port with `python3 -m app serve --port 9000`. On first start,
`config/kit.config.json` is created from `config/kit.config.example.json`.

### Command line (no browser)

```bash
python3 -m app validate                 # check config, paths, compiler, test file; runs nothing
python3 -m app run                      # build + test with the saved config, write the report
python3 -m app report <RUN_ID> [--sample --out docs/x.html]   # re-render a recorded run's report
```

`run` exits with 0 for `PASSED`/`PASSED_WITH_SKIPS` and 1 otherwise, so it can be used in CI.

## Configuration guide

`config/kit.config.json` is the single source of truth. Edit it in the browser or by hand:

```json
{
  "project_name": "PREMCALC demo",
  "compiler": {
    "adapter": "gnucobol",
    "executable": "cobc",
    "args": ["-x", "-free", "-Wall"],
    "timeout_seconds": 60
  },
  "paths": {
    "source_dir": "samples/src",
    "source_file": "PREMCALC.cbl",
    "build_dir": "build",
    "tests_file": "samples/tests/premcalc_tests.json",
    "report_dir": "reports"
  },
  "run": { "default_test_timeout_seconds": 5, "max_output_bytes": 65536 }
}
```

- **Default flags:** `-x` builds an executable, `-free` matches the sample's free-format
  source, and `-Wall` shows warnings in the compiler log. For fixed-format sources, drop
  `-free` (or use `-fixed`).
- **Paths** are relative to the project folder (absolute paths are allowed) and must
  resolve *inside* it. `source_file` must be inside `source_dir`. Paths with spaces work.
- **Flags field (UI):** split with POSIX shell quoting rules (`-I "copy books"` is two
  arguments), stored as a JSON array and passed straight to the process. There is **no**
  variable expansion, globbing, pipes or `;`. Those characters become literal arguments.
  Limitation: a flag that must contain a line break cannot be entered.
- Runs always use the **saved** configuration. The UI warns you about unsaved changes.

### Using a different compiler without changing code

There are two adapters (`app/compilers.py`):

| Adapter | Command built |
|---|---|
| `gnucobol` | `<executable> <args...> -o <build_dir>/<PROGRAM> <source>` |
| `generic` | `<executable> <args...>`, where an argument that is exactly `{source}` or `{output}` is replaced by the path |

Examples:

- Another GnuCOBOL install: set `executable` to `/opt/gnucobol-3.2/bin/cobc`.
- Fixed format: set the flags to `-x -fixed -Wall`.
- Any other command-line compiler: set `adapter` to `generic` and give args like
  `["-x", "-free", "-o", "{output}", "{source}"]`, or whatever that compiler expects.

A compiler with a very different workflow (a mainframe JCL submit, multi-step link,
copybook libraries or DB2 precompile) needs a new adapter class in `app/compilers.py`
with `check_args` and `build_command`, registered in `ADAPTERS`. Nothing else has to change.

## Test case format

JSON (see [`samples/tests/premcalc_tests.json`](samples/tests/premcalc_tests.json)):

```json
{
  "suite": "PREMCALC premium calculation",
  "default_timeout_seconds": 5,
  "tests": [
    {
      "id": "TC-001",
      "category": "normal",
      "description": "Standard driver, no claims",
      "input": "35,20000,0",
      "expected": { "stdout": "RESULT=OK PREMIUM=700.00", "exit_code": 0 },
      "compare": "exact",
      "timeout_seconds": 5,
      "enabled": true
    }
  ]
}
```

**How a test runs:** the built program runs once per test with `build_dir` as the working
directory. `input` plus a newline goes to **stdin**, and **stdout**, **stderr** and the
**exit code** are captured. Tests run in file order, one at a time.

**Comparison rules** (`compare`):

| Mode | Passes when |
|---|---|
| `exact` | stdout equals `expected.stdout` after normalisation |
| `contains` | `expected.stdout` appears in the normalised stdout |
| `regex` | Python `re.search(expected.stdout, stdout, MULTILINE)` matches |
| `exit_code` | only the exit code is checked |

Normalisation: CRLF becomes LF, trailing spaces are removed from each line (COBOL `DISPLAY`
pads fields), and leading/trailing blank lines are dropped. If `expected.exit_code` is set,
it is checked in **every** mode.

**Statuses:** `PASS`; `FAIL` (comparison failed); `ERROR` (timed out or could not start);
`NOT RUN` (disabled, or the build failed). A test that was not executed is never counted
as passed.
Overall: `PASSED`, `PASSED_WITH_SKIPS`, `FAILED`, `BUILD_FAILED`, `NO_TESTS_RUN`, `ERROR` (setup problem).

### Sample program interface (PREMCALC)

- **stdin:** one line `AGE,VEHICLE-VALUE,CLAIMS`.
- **stdout:** `RESULT=OK PREMIUM=n.nn`, `RESULT=DECLINED REASON=TOO-MANY-CLAIMS`
  or `RESULT=ERROR CODE=Enn MSG=...`.
- **Exit code:** 0, or 4 on invalid input.

The rules are documented in the header of [`samples/src/PREMCALC.cbl`](samples/src/PREMCALC.cbl).
Expected values in the sample suite were computed by hand from those rules. `TC-014` is
deliberately disabled, to show how a pending business rule appears as `NOT RUN`.

## Claude Code integration

`.claude/skills/cobol-test-workflow/SKILL.md` tells Claude Code how to:
- inspect the config and source, and explain the program
- propose test cases, labelling each as *confirmed* or *inferred*
- run only the documented commands, and read the real run records
- diagnose failures without changing expectations or masking failures, and propose code fixes for review instead of applying them
- refresh the report and summarize the evidence

Example invocation, inside Claude Code at the repository root:

```
/cobol-test-workflow Explain PREMCALC, propose missing boundary tests for vehicle value,
then run the suite and summarize the results with evidence.
```

## Running the kit's own tests

```bash
python3 -m unittest discover -s tests -t . -v
```

The suite covers:
- config validation, flag parsing and path containment
- process execution: exit codes, stdin, timeouts including child processes, truncation, no shell
- comparison rules and status calculation
- the full workflow with a fake compiler: pass, fail, error, not run, compile failure, missing compiler, compile timeout, stale binary
- HTML escaping and path sanitising in reports
- HTTP safety: host/origin checks, JSON-only POSTs, whitelisted static files
- `test_cobc_integration.py` with real GnuCOBOL, **skipped** when `cobc` is not installed: sample in a path with spaces, a wrong expectation staying FAIL, compile failure, infinite-loop timeout, generic adapter

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Compiler 'cobc' not found" | Install GnuCOBOL, or set the full path in *Compiler executable*. |
| Build FAILED with format errors | Source format and flags disagree: use `-free` for free format, `-fixed` (or nothing) for fixed. |
| `libcob` errors when tests run | Compiler/runtime mismatch. Run `cobc --info` and check the install. |
| Test ERROR "Timed out" | The program waits for more input or loops. Check the stdin protocol, or raise that test's `timeout_seconds` if the run is genuinely slow. |
| "resolves outside the project directory" | Keep sources, tests, build and reports inside this folder (or a subfolder). |
| Port already in use | `python3 -m app serve --port 9000` |
| 403 "Host not allowed" | Open the app through `127.0.0.1` or `localhost`, not another hostname. |

## Security model and limitations

This v1 is for **local, trusted, single-user** use. It is not a multi-user or public server.

- It binds to `127.0.0.1` by default and warns when bound elsewhere.
- No endpoint runs arbitrary commands. The only actions are save/validate config, start a
  run and read results. The compiler is launched from an argument list (`shell=False`), and
  the program under test runs only through the test runner.
- POST requests must be JSON with a matching `Host`/`Origin`. This blocks cross-site form
  posts and DNS-rebinding requests.
- All paths are validated server-side to stay inside the project. The only files the tool
  deletes are its own previous build output for the configured program, so a failed compile
  can never run a stale binary.
- Processes have timeouts. The whole process group is killed on timeout, and output is
  capped (`max_output_bytes`).
- Pages use a strict Content-Security-Policy, and dynamic text is inserted with
  `textContent`. Reports escape every value, contain no scripts and load nothing remotely.
- Reports shorten local paths to `<project>` and `~`. The run records in `runs/` keep the
  full paths.
- The **compiler executable is trusted**: whoever can edit the config can choose which
  program is run as the compiler. Do not expose this tool to untrusted users.
- The tool never edits COBOL source or expected results to "fix" failures.
- Limitations: one program per configuration, stdin/stdout programs only (no file or
  database fixtures yet), one run at a time, no pre/post-build steps in v1. Windows is
  untested; it was developed on macOS, and Linux is the main target.

## Project layout

```
app/            config, compiler adapters, process runner, test runner, report, server, CLI
static/         Configuration and Results pages (HTML/CSS/JS)
config/         kit.config.example.json (kit.config.json is local and git-ignored)
samples/        synthetic COBOL program and test cases
tests/          unittest suite
docs/           getting-started guide, sample report
.github/        CI: unit tests + sample run on Ubuntu with GnuCOBOL
.claude/skills/ Claude Code skill
runs/ build/ reports/   generated at runtime (git-ignored)
```

## License

MIT. See [LICENSE](LICENSE).
