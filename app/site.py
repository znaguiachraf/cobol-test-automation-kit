"""Static website export for publishing results on plain web hosting (e.g. cPanel shared hosting).

The site is a folder of HTML files with inline CSS only: no scripts, no server code,
nothing loaded remotely. It contains the run history, one report per run, the test
suite and the COBOL source. Every value is escaped with ``report.esc`` and local
paths are shortened with ``report.sanitize``. Nothing in the site can start a build.
"""

import json
from pathlib import Path

from . import TOOL_NAME, config as config_mod, report, testcases
from .config import PROJECT_ROOT
from .report import badge, esc

MAX_RUNS = 50

# Apache (cPanel) settings: the same CSP as the local report view, no directory listings.
HTACCESS = """\
Options -Indexes
AddType application/json .json
<IfModule mod_headers.c>
  Header always set Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"
  Header always set X-Content-Type-Options "nosniff"
  Header always set X-Frame-Options "DENY"
  Header always set Referrer-Policy "no-referrer"
</IfModule>
"""

SITE_CSS = """
nav{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0 0 20px;padding-bottom:10px;border-bottom:1px solid var(--line)}
nav a{color:var(--accent);text-decoration:none;font-weight:600}nav a[aria-current]{color:var(--fg)}
a{color:var(--accent)}
.scroll{overflow-x:auto}
.notice{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:16px 0 0}
pre.src{white-space:pre;overflow-x:auto;word-break:normal}
"""

NAV = (("index.html", "Results"), ("tests.html", "Test cases"), ("source.html", "COBOL source"))
CURRENT = ' aria-current="page"'


def sanitize_data(value, root=PROJECT_ROOT):
    """Return ``value`` with local paths shortened in every string (for published JSON)."""
    if isinstance(value, str):
        return report.sanitize(value, root)
    if isinstance(value, list):
        return [sanitize_data(v, root) for v in value]
    if isinstance(value, dict):
        return {k: sanitize_data(v, root) for k, v in value.items()}
    return value


def _page(title, current, body, project_name):
    nav = "".join(
        f"<a href='{href}'{CURRENT if href == current else ''}>{esc(label)}</a>" for href, label in NAV)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} - {esc(project_name)}</title>"
            f"<style>{report.CSS}{SITE_CSS}</style></head><body><main>"
            f"<h1>{esc(project_name)}</h1><p class='sub'>{esc(TOOL_NAME)}</p>"
            f"<nav>{nav}</nav>{body}"
            "<footer>Static, read-only publication. Builds and tests run in CI with GnuCOBOL; "
            "this site cannot start a run. Local paths are shortened to &lt;project&gt; and ~.</footer>"
            "</main></body></html>")


def render_index(runs, project_name):
    out = []
    w = out.append
    if not runs:
        w("<p class='notice'>No runs have been published yet.</p>")
        return _page("Results", "index.html", "".join(out), project_name)
    latest = runs[0]
    s = latest.get("summary") or {}
    w(f"<h2>Latest run <code>{esc(latest.get('run_id'))}</code></h2>")
    w(f"<p class='sub'>Started {esc(latest.get('started_at'))} &middot; "
      f"<a href='reports/report-{esc(latest.get('run_id'))}.html'>Full report</a></p>")
    w("<div class='hero'>")
    w(f"<div class='stat'><span>Overall</span><b>{badge(latest.get('status'))}</b></div>")
    for key, label in (("total", "Total"), ("passed", "Passed"), ("failed", "Failed"),
                       ("errors", "Errors"), ("not_run", "Not run")):
        w(f"<div class='stat'><span>{label}</span><b>{esc(s.get(key, 0))}</b></div>")
    w("</div>")

    w(f"<h2>History ({len(runs)} run{'s' if len(runs) != 1 else ''})</h2><div class='scroll'><table>")
    w("<thead><tr><th>Run</th><th>Started</th><th>Build</th><th>Status</th><th>Passed</th>"
      "<th>Failed</th><th>Errors</th><th>Not run</th><th>Report</th></tr></thead><tbody>")
    for run in runs:
        s = run.get("summary") or {}
        rid = esc(run.get("run_id"))
        w(f"<tr><td><code>{rid}</code></td><td>{esc(run.get('started_at'))}</td>"
          f"<td>{badge((run.get('build') or {}).get('status'))}</td><td>{badge(run.get('status'))}</td>"
          f"<td>{esc(s.get('passed', 0))}</td><td>{esc(s.get('failed', 0))}</td>"
          f"<td>{esc(s.get('errors', 0))}</td><td>{esc(s.get('not_run', 0))}</td>"
          f"<td><a href='reports/report-{rid}.html'>View</a></td></tr>")
    w("</tbody></table></div>")
    return _page("Results", "index.html", "".join(out), project_name)


def render_tests(suite, project_name, error=None):
    out = []
    w = out.append
    if error:
        w(f"<p class='notice'>The test file could not be loaded: {esc(error)}</p>")
        return _page("Test cases", "tests.html", "".join(out), project_name)
    tests = suite["tests"]
    w(f"<h2>{esc(suite['suite'])} ({len(tests)} test{'s' if len(tests) != 1 else ''})</h2>")
    w("<div class='scroll'><table><thead><tr><th>ID</th><th>Description</th><th>Input (stdin)</th>"
      "<th>Expected</th><th>Compare</th><th>Enabled</th></tr></thead><tbody>")
    for t in tests:
        enabled = "yes" if t["enabled"] else f"no{(' - ' + t['skip_reason']) if t['skip_reason'] else ''}"
        w(f"<tr><td><code>{esc(t['id'])}</code></td>"
          f"<td>{esc(t['description'])}<br><span class='muted'>{esc(t['category'])}</span></td>"
          f"<td><pre>{esc(t['input'])}</pre></td><td><pre>{esc(report._expected_text(t))}</pre></td>"
          f"<td>{esc(t['compare'])}</td><td>{esc(enabled)}</td></tr>")
    w("</tbody></table></div>")
    return _page("Test cases", "tests.html", "".join(out), project_name)


def render_source(name, text, project_name, error=None):
    if error:
        body = f"<p class='notice'>The source file could not be read: {esc(error)}</p>"
    else:
        body = f"<h2><code>{esc(name)}</code></h2><pre class='src'>{esc(text)}</pre>"
    return _page("COBOL source", "source.html", body, project_name)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def export_site(runs, cfg, out_dir, root=PROJECT_ROOT):
    """Write the static site for ``runs`` (newest first) into ``out_dir``. Returns ``out_dir``."""
    out_dir = Path(out_dir)
    root = Path(root)
    runs = [sanitize_data(run, root) for run in runs[:MAX_RUNS]]
    project_name = cfg.get("project_name") or TOOL_NAME
    paths = config_mod.resolved_paths(cfg, root)

    _write(out_dir / "index.html", render_index(runs, project_name))
    for run in runs:
        _write(out_dir / "reports" / f"report-{run['run_id']}.html", report.render_report(run, root=root))
        _write(out_dir / "data" / "runs" / f"{run['run_id']}.json", json.dumps(run, indent=2))
    _write(out_dir / "data" / "index.json", json.dumps({"runs": [r["run_id"] for r in runs]}, indent=2))

    try:
        suite, error = testcases.load_suite(paths["tests_file"]), None
    except testcases.TestFileError as exc:
        suite, error = None, report.sanitize(str(exc), root)
    _write(out_dir / "tests.html", render_tests(suite, project_name, error))

    source = paths["source_file"]
    try:
        text, error = source.read_text("utf-8", errors="replace"), None
    except OSError as exc:
        text, error = "", report.sanitize(str(exc), root)
    _write(out_dir / "source.html", render_source(source.name, text, project_name, error))

    _write(out_dir / ".htaccess", HTACCESS)
    return out_dir
