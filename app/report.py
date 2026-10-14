"""Standalone HTML test report generated from a recorded run.

Every value from the run (program output, test data, paths, config) is
treated as untrusted and passed through ``esc`` before it is rendered.
The report has inline CSS only: no scripts, remote fonts or CDNs.
"""

import html
import os
from datetime import datetime
from pathlib import Path

from . import TOOL_NAME
from .config import PROJECT_ROOT

STATUS_CLASS = {
    "PASS": "ok", "PASSED": "ok", "SUCCESS": "ok",
    "PASSED_WITH_SKIPS": "warn", "NOT RUN": "muted", "NO_TESTS_RUN": "warn",
    "FAIL": "bad", "FAILED": "bad", "ERROR": "bad", "BUILD_FAILED": "bad",
}


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def sanitize(text, root=PROJECT_ROOT):
    """Hide machine-specific absolute paths in logs (project root -> '<project>', home -> '~')."""
    if not text:
        return ""
    text = str(text).replace(str(Path(root).resolve()), "<project>")
    home = os.path.expanduser("~")
    if home and home != "/":
        text = text.replace(home, "~")
    return text


def badge(status):
    label = str(status).replace("_", " ")
    return f'<span class="badge {STATUS_CLASS.get(status, "muted")}">{esc(label)}</span>'


def _pre(text, root):
    text = sanitize(text, root)
    return f"<pre>{esc(text)}</pre>" if text.strip() else '<p class="muted">(empty)</p>'


def _expected_text(test):
    exp = test.get("expected") or {}
    parts = []
    if exp.get("stdout") is not None:
        parts.append(f"stdout [{test.get('compare')}]: {exp['stdout']}")
    if exp.get("exit_code") is not None:
        parts.append(f"exit code: {exp['exit_code']}")
    return "\n".join(parts)


def _actual_text(test):
    act = test.get("actual")
    if not act:
        return ""
    parts = [act.get("stdout", "").rstrip()]
    parts.append(f"exit code: {act.get('exit_code') if act.get('exit_code') is not None else 'n/a'}")
    return "\n".join(p for p in parts if p)


CSS = """
:root{--fg:#1d2433;--muted:#5d6678;--line:#d9dee7;--bg:#ffffff;--panel:#f5f7fa;
--ok:#116329;--ok-bg:#dafbe1;--bad:#a40e26;--bad-bg:#ffe1e4;--warn:#7a4d00;--warn-bg:#fff1c2;--accent:#0b5cad}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 20px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:14px;margin:16px 0 6px}
.sub{color:var(--muted);margin:0}
.sample{border:2px dashed var(--warn);background:var(--warn-bg);color:var(--warn);padding:10px 14px;border-radius:6px;font-weight:600;margin-bottom:16px}
.hero{display:flex;flex-wrap:wrap;gap:12px;margin-top:20px}
.stat{flex:1 1 120px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.stat b{display:block;font-size:22px;font-variant-numeric:tabular-nums}.stat span{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:7px 8px;border-bottom:1px solid var(--line)}
th{background:var(--panel);font-weight:600}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}dt{color:var(--muted)}dd{margin:0;word-break:break-word}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px;margin:4px 0;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
td pre{margin:0;padding:6px}
code{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.ok{background:var(--ok-bg);color:var(--ok)}.bad{background:var(--bad-bg);color:var(--bad)}
.warn{background:var(--warn-bg);color:var(--warn)}.muted{color:var(--muted)}
.badge.muted{background:var(--panel);border:1px solid var(--line)}
.failure{border-left:4px solid var(--bad);padding:4px 12px;margin:12px 0}
ul{margin:6px 0;padding-left:20px}
footer{margin-top:40px;color:var(--muted);font-size:12px}
@media print{main{padding:0;max-width:none}h2{break-after:avoid}tr,pre,.failure{break-inside:avoid}}
"""


def render_report(run, sample=False, root=PROJECT_ROOT):
    """Return the report as an HTML string built only from ``run``."""
    s = run.get("summary") or {}
    build = run.get("build") or {}
    cfg = run.get("config") or {}
    env = run.get("environment") or {}
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    out = []
    w = out.append

    w("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    w(f"<title>{'SAMPLE - ' if sample else ''}Test report {esc(run.get('run_id'))}</title>")
    w(f"<style>{CSS}</style></head><body><main>")
    if sample:
        w("<div class='sample'>SAMPLE REPORT - generated from a demo run of synthetic code and data. "
          "It is an example of the report format, not evidence for any real system.</div>")
    w(f"<h1>{esc(TOOL_NAME)} - Test Report</h1>")
    w(f"<p class='sub'>{esc(run.get('project_name'))} &middot; suite: {esc(run.get('suite') or 'n/a')}</p>")
    w(f"<p class='sub'>Run <code>{esc(run.get('run_id'))}</code> &middot; report generated {esc(generated)}</p>")

    w("<div class='hero'>")
    w(f"<div class='stat'><span>Overall</span><b>{badge(run.get('status'))}</b></div>")
    for key, label in (("total", "Total"), ("passed", "Passed"), ("failed", "Failed"),
                       ("errors", "Errors"), ("not_run", "Not run")):
        w(f"<div class='stat'><span>{label}</span><b>{esc(s.get(key, 0))}</b></div>")
    w("</div>")

    w("<h2>Run and environment</h2><dl>")
    rows = [
        ("Started", run.get("started_at")), ("Ended", run.get("ended_at")),
        ("Tool version", (run.get("tool") or {}).get("version")),
        ("Platform", env.get("platform")), ("Python", env.get("python")),
        ("Compiler", env.get("compiler_version") or "not recorded"),
    ]
    for k, v in rows:
        w(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>")
    w("</dl>")

    w("<h2>Configuration summary</h2><dl>")
    comp, paths = cfg.get("compiler") or {}, cfg.get("paths") or {}
    rows = [
        ("Adapter", comp.get("adapter")), ("Compiler executable", sanitize(comp.get("executable"), root)),
        ("Compiler arguments", " ".join(comp.get("args") or []) or "(none)"),
        ("Compile timeout", f"{comp.get('timeout_seconds')} s"),
        ("Source", f"{paths.get('source_dir')}/{paths.get('source_file')}"),
        ("Tests file", paths.get("tests_file")), ("Build directory", paths.get("build_dir")),
        ("Default test timeout", f"{(cfg.get('run') or {}).get('default_test_timeout_seconds')} s"),
    ]
    for k, v in rows:
        w(f"<dt>{esc(k)}</dt><dd>{esc(sanitize(v, root))}</dd>")
    w("</dl>")

    w("<h2>Compilation</h2><dl>")
    w(f"<dt>Status</dt><dd>{badge(build.get('status'))}</dd>")
    w(f"<dt>Exit code</dt><dd>{esc(build.get('exit_code') if build.get('exit_code') is not None else 'n/a')}</dd>")
    if build.get("duration_ms") is not None:
        w(f"<dt>Duration</dt><dd>{esc(build.get('duration_ms'))} ms</dd>")
    if build.get("command"):
        w(f"<dt>Command</dt><dd><code>{esc(sanitize(' '.join(build['command']), root))}</code></dd>")
    if build.get("error"):
        w(f"<dt>Error</dt><dd>{esc(sanitize(build['error'], root))}</dd>")
    w("</dl>")
    w("<h3>Compiler stdout</h3>" + _pre(build.get("stdout"), root))
    w("<h3>Compiler stderr</h3>" + _pre(build.get("stderr"), root))

    w("<h2>Test cases</h2>")
    tests = run.get("tests") or []
    if tests:
        w("<table><thead><tr><th>ID</th><th>Description</th><th>Input</th><th>Expected</th>"
          "<th>Actual</th><th>Status</th><th>Time</th></tr></thead><tbody>")
        for t in tests:
            dur = f"{t['duration_ms']} ms" if t.get("duration_ms") is not None else "-"
            w(f"<tr><td><code>{esc(t.get('id'))}</code></td>"
              f"<td>{esc(t.get('description'))}<br><span class='muted'>{esc(t.get('category'))}</span></td>"
              f"<td><pre>{esc(t.get('input'))}</pre></td>"
              f"<td><pre>{esc(_expected_text(t))}</pre></td>"
              f"<td><pre>{esc(sanitize(_actual_text(t), root)) or '-'}</pre></td>"
              f"<td>{badge(t.get('status'))}</td><td>{esc(dur)}</td></tr>")
        w("</tbody></table>")
    else:
        w("<p class='muted'>No test cases were loaded for this run.</p>")

    problems = [t for t in tests if t.get("status") in ("FAIL", "ERROR")]
    w("<h2>Failures and diagnostics</h2>")
    if not problems and build.get("status") == "SUCCESS":
        w("<p>No failed or errored tests in this run.</p>")
    if build.get("status") not in (None, "SUCCESS"):
        w("<div class='failure'><b>Build did not succeed.</b> Review the compiler stderr above. "
          "Tests depending on the build were not executed.</div>")
    for t in problems:
        act = t.get("actual") or {}
        w(f"<div class='failure'><b>{esc(t.get('id'))}</b> {badge(t.get('status'))} - {esc(t.get('description'))}<ul>")
        for reason in t.get("reasons") or []:
            w(f"<li>{esc(sanitize(reason, root))}</li>")
        w("</ul>")
        if act.get("stderr", "").strip():
            w("<h3>Program stderr</h3>" + _pre(act["stderr"], root))
        w("</div>")

    w("<h2>Limitations and tests not executed</h2><ul>")
    for note in run.get("notes") or []:
        w(f"<li>{esc(sanitize(note, root))}</li>")
    for t in tests:
        if t.get("status") == "NOT RUN":
            w(f"<li><code>{esc(t.get('id'))}</code> not run: {esc('; '.join(t.get('reasons') or []))}</li>")
    for c in run.get("checks") or []:
        if c.get("status") == "error":
            w(f"<li>Validation error ({esc(c.get('name'))}): {esc(sanitize(c.get('message'), root))}</li>")
    w("<li>Results show only what the test cases check. Expected values and business rules require human review; "
      "a passing run does not prove the program is correct.</li></ul>")

    w(f"<footer>Generated by {esc(TOOL_NAME)} from the recorded run data in runs/{esc(run.get('run_id'))}.json. "
      "Local paths are shortened to &lt;project&gt; and ~.</footer>")
    w("</main></body></html>")
    return "".join(out)


def write_report(run, report_dir, sample=False, root=PROJECT_ROOT, filename=None):
    """Write the report and return its path. Only ``report-<run_id>.html`` (or ``filename``) is written."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / (filename or f"report-{run['run_id']}.html")
    path.write_text(render_report(run, sample=sample, root=root), encoding="utf-8")
    return path
