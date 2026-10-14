"""HTTP-level tests. They never call the save or run endpoints, so the real config is untouched."""

import http.client
import json
import tempfile
import threading
import unittest

from app import service
from app.server import make_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.httpd = make_server("127.0.0.1", 0, manager=service.RunManager(runs_dir=cls.tmp.name))
        cls.httpd.quiet = True
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def test_pages_and_security_headers(self):
        for path in ("/config", "/results"):
            resp, data = self.request("GET", path)
            self.assertEqual(resp.status, 200)
            self.assertIn(b"<!doctype html>", data)
            self.assertIn("script-src 'self'", resp.getheader("Content-Security-Policy"))
            self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")

    def test_only_whitelisted_static_files(self):
        self.assertEqual(self.request("GET", "/static/config.js")[0].status, 200)
        for path in ("/static/../app/config.py", "/static/%2e%2e/app/server.py", "/static/missing.js", "/app/config.py"):
            self.assertEqual(self.request("GET", path)[0].status, 404, path)

    def test_unknown_host_rejected(self):
        resp, _ = self.request("GET", "/api/config", headers={"Host": "attacker.example"})
        self.assertEqual(resp.status, 403)

    def test_cross_origin_post_rejected(self):
        resp, _ = self.request("POST", "/api/run", body="{}",
                               headers={"Content-Type": "application/json", "Origin": "http://attacker.example"})
        self.assertEqual(resp.status, 403)

    def test_non_json_post_rejected(self):
        resp, _ = self.request("POST", "/api/run", body="a=1",
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(resp.status, 400)

    def test_validate_reports_errors_without_saving(self):
        body = json.dumps({"config": {"compiler": {"adapter": "gnucobol", "executable": "", "args": ["-o", "x"]},
                                      "paths": {}, "run": {}}})
        resp, data = self.request("POST", "/api/validate", body=body,
                                  headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status, 400)
        payload = json.loads(data)
        self.assertTrue(any("compiler.executable" in e for e in payload["errors"]))
        self.assertTrue(all(c["status"] == "error" for c in payload["checks"]))

    def test_no_arbitrary_command_endpoint(self):
        for path in ("/api/exec", "/api/shell", "/api/command"):
            resp, _ = self.request("POST", path, body=json.dumps({"cmd": "ls"}),
                                   headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status, 404)

    def test_unknown_run_and_report(self):
        self.assertEqual(self.request("GET", "/api/runs/20990101-000000-abcd")[0].status, 404)
        self.assertEqual(self.request("GET", "/reports/..%2f..%2fetc%2fpasswd")[0].status, 404)


if __name__ == "__main__":
    unittest.main()
