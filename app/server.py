"""Local HTTP server for the Configuration and Results pages (standard library only).

Safety model (local, trusted, single-user tool):
  * binds to 127.0.0.1 by default;
  * only fixed actions are exposed (save/validate config, start a run, read
    results) - there is no endpoint that executes a caller-supplied command;
  * POST requests must be JSON and same-origin (Origin/Host checks), which
    blocks cross-site form posts and DNS-rebinding requests;
  * all paths in the config are validated server-side to stay in the project.
"""

import json
import mimetypes
import re
import shlex
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import compilers, config as config_mod, service, store

STATIC_DIR = config_mod.PROJECT_ROOT / "static"
PAGES = {"/config": "config.html", "/results": "results.html"}
STATIC_FILES = {"style.css", "common.js", "config.js", "results.js"}
MAX_BODY = 64 * 1024

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
PAGE_CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'none'"
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"


def command_preview(cfg):
    """The build argument list this config would produce (display only; nothing is run)."""
    try:
        paths = config_mod.resolved_paths(cfg)
    except config_mod.ConfigError:
        return None
    output = paths["build_dir"] / compilers.executable_name(paths["source_file"].stem)
    adapter = compilers.ADAPTERS[cfg["compiler"]["adapter"]]
    root = str(config_mod.PROJECT_ROOT)
    return [a.replace(root, ".") for a in adapter.build_command(
        cfg["compiler"]["executable"], cfg["compiler"]["args"], paths["source_file"], output)]


def config_payload(cfg, checks=None):
    return {
        "config": cfg,
        "command_preview": command_preview(cfg),
        "args_text": shlex.join(cfg["compiler"]["args"]),
        "adapters": {name: a.description for name, a in compilers.ADAPTERS.items()},
        "config_file": str(config_mod.CONFIG_PATH.relative_to(config_mod.PROJECT_ROOT)),
        "checks": checks,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "CobolTestKit"
    sys_version = ""

    # --- helpers -----------------------------------------------------------------
    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _send(self, status, body, content_type, extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in {**BASE_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload), "application/json; charset=utf-8")

    def _error(self, status, message, errors=None):
        self._json(status, {"error": message, "errors": errors or [message]})

    def _host_ok(self):
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if origin is None:  # non-browser clients (curl, tests) do not send Origin
            return True
        parts = urlsplit(origin)
        return parts.scheme == "http" and parts.netloc in self.server.allowed_hosts

    def _read_json(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    # --- routing -----------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Host not allowed")
        path = urlsplit(self.path).path
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/config")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if path in PAGES:
            return self._static(PAGES[path], csp=True)
        if path.startswith("/static/") and path[len("/static/"):] in STATIC_FILES:
            return self._static(path[len("/static/"):])
        if path == "/api/config":
            try:
                cfg = config_mod.load_config()
            except (config_mod.ConfigError, ValueError) as exc:
                errors = getattr(exc, "errors", [str(exc)])
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                                   f"Config file {config_mod.CONFIG_PATH.name} is invalid", errors)
            return self._json(HTTPStatus.OK, config_payload(cfg))
        if path == "/api/status":
            return self._json(HTTPStatus.OK, self.server.manager.status())
        if path == "/api/runs":
            return self._json(HTTPStatus.OK, {"runs": store.list_runs(self.server.manager.runs_dir)})
        match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if match:
            run = store.load_run(match.group(1), self.server.manager.runs_dir)
            if run is None:
                return self._error(HTTPStatus.NOT_FOUND, "Run not found")
            run["report_available"] = service.report_path_for(run, self.server.manager.root) is not None
            return self._json(HTTPStatus.OK, run)
        match = re.fullmatch(r"/reports/([^/]+)", path)
        if match:
            run = store.load_run(match.group(1), self.server.manager.runs_dir)
            report_path = service.report_path_for(run, self.server.manager.root) if run else None
            if report_path is None:
                return self._error(HTTPStatus.NOT_FOUND, "Report not found")
            return self._send(HTTPStatus.OK, report_path.read_bytes(), "text/html; charset=utf-8",
                              {"Content-Security-Policy": REPORT_CSP})
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        if not self._host_ok() or not self._same_origin():
            return self._error(HTTPStatus.FORBIDDEN, "Cross-origin or unknown-host request rejected")
        path = urlsplit(self.path).path
        try:
            body = self._read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, f"Invalid request: {exc}")

        if path in ("/api/config", "/api/validate"):
            try:
                cfg = config_mod.normalize(body.get("config") if isinstance(body, dict) else None)
            except config_mod.ConfigError as exc:
                return self._json(HTTPStatus.BAD_REQUEST, {
                    "error": "Configuration is invalid", "errors": exc.errors,
                    "checks": [{"name": "Configuration values", "status": "error", "message": m} for m in exc.errors],
                })
            checks = config_mod.validate_environment(cfg)
            if path == "/api/config":
                config_mod.save_config(cfg)
            return self._json(HTTPStatus.OK, config_payload(cfg, checks) | {"saved": path == "/api/config"})

        if path == "/api/run":
            try:
                cfg = config_mod.load_config()
            except (config_mod.ConfigError, ValueError) as exc:
                return self._error(HTTPStatus.BAD_REQUEST, "Saved configuration is invalid",
                                   getattr(exc, "errors", [str(exc)]))
            run_id = self.server.manager.start(cfg)
            if run_id is None:
                return self._error(HTTPStatus.CONFLICT, "A run is already in progress")
            return self._json(HTTPStatus.ACCEPTED, {"run_id": run_id})
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def _static(self, name, csp=False):
        path = STATIC_DIR / name
        if not path.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "Not found")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, path.read_bytes(), ctype,
                   {"Content-Security-Policy": PAGE_CSP} if csp else None)


def make_server(host="127.0.0.1", port=8765, manager=None):
    httpd = ThreadingHTTPServer((host, port), Handler)
    actual_port = httpd.server_address[1]
    httpd.allowed_hosts = {f"{h}:{actual_port}" for h in {host, "127.0.0.1", "localhost"}}
    httpd.manager = manager or service.RunManager()
    return httpd
