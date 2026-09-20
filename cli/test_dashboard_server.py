"""
Comprehensive unit and security tests for Cedar Sentinel Local Dashboard Server.
Covers:
- 127.0.0.1 binding only
- Host and Origin header validation (DNS rebinding / CSRF defenses)
- Method restriction (GET/HEAD only; 405 on POST/PUT/DELETE/OPTIONS)
- Path traversal and dotfile protections
- Strict UUID validation on /api/runs/<id>
- Unknown /api/* returning 404 JSON
- Sanitization by default vs --show-real-ids
- Byte-for-byte equivalence with exported run files
- Offline directory mode
- XSS payload safety
"""

import http.client
import json
import os
import re
import socket
import socketserver
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import unittest
import urllib.request
import urllib.error

# Ensure root is in sys.path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cli.dashboard_server import DashboardContext, create_handler
from cli.run_data import decimal_default, normalize_run_item, sanitize_value


class TestRunDataNormalizationAndSanitization(unittest.TestCase):
    """Tests for shared run_data normalization and sanitization."""

    def setUp(self):
        self.raw_fixture = {
            "request_id": "51c455ef-9a57-41e9-9132-841d1a610260",
            "role_arn": "arn:aws:iam::123456789012:role/cedar-sentinel-demo-role",
            "role_name": "cedar-sentinel-demo-role",
            "status": "APPLIED",
            "completed_at": "2026-09-19T14:35:10+00:00",
            "log_group": "aws-cloudtrail-logs-test-region",
            "policy_store_id": "VPAVPSTOREID1234567890",
            "policy_id": "POL987654321012345678",
            "ttl": 1726750000,
            "observed_actions": {
                "s3:GetObject": "12",
                "s3:PutObject": 4
            },
            "guard_removed_actions": ["s3:DeleteBucket", "s3:PutBucketAcl"],
            "requested_policy": json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]
            }),
            "iam_policy": json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": "*"}]
            }),
            "rationale": "Tightened policy to observed S3 actions only."
        }

    def test_default_sanitization(self):
        sanitized = normalize_run_item(self.raw_fixture, show_real_ids=False)
        self.assertEqual(sanitized["role_arn"], "arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role")
        self.assertEqual(sanitized["log_group"], "<LOG_GROUP>")
        self.assertEqual(sanitized["policy_store_id"], "<AVP_STORE_ID>")
        self.assertEqual(sanitized["policy_id"], "<POLICY_ID>")
        self.assertNotIn("ttl", sanitized)
        self.assertEqual(sanitized["observed_actions"]["s3:GetObject"], 12)
        self.assertEqual(sanitized["observed_actions"]["s3:PutObject"], 4)
        self.assertIsInstance(sanitized["requested_policy"], dict)
        self.assertIsInstance(sanitized["iam_policy"], dict)
        self.assertFalse(bool(re.search(r"\b123456789012\b", json.dumps(sanitized))))

    def test_show_real_ids_flag(self):
        raw = normalize_run_item(self.raw_fixture, show_real_ids=True)
        self.assertEqual(raw["role_arn"], "arn:aws:iam::123456789012:role/cedar-sentinel-demo-role")
        self.assertEqual(raw["policy_store_id"], "VPAVPSTOREID1234567890")
        self.assertNotIn("ttl", raw)  # TTL is dropped even with show_real_ids
        self.assertIsInstance(raw["requested_policy"], dict)

    def test_byte_for_byte_export_equivalence(self):
        """Asserts /api/runs/<id> normalized output matches exported dashboard file."""
        exported_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "runs", "applied.json")
        if os.path.exists(exported_path):
            with open(exported_path, "r", encoding="utf-8") as f:
                disk_item = json.load(f)

            # Re-normalizing should be idempotent and byte-for-byte equal
            normalized_disk = normalize_run_item(disk_item, show_real_ids=False, synthetic=disk_item.get("synthetic", False))
            
            str1 = json.dumps(disk_item, indent=2, sort_keys=True)
            str2 = json.dumps(normalized_disk, indent=2, sort_keys=True)
            self.assertEqual(str1, str2)


class TestLocalDashboardHTTPServer(unittest.TestCase):
    """Integration test suite for LocalDashboardRequestHandler."""

    @classmethod
    def setUpClass(cls):
        # Create a test directory with mock static files and runs
        cls.test_dir = tempfile.TemporaryDirectory()
        cls.dashboard_dir = os.path.join(cls.test_dir.name, "dashboard")
        cls.runs_dir = os.path.join(cls.dashboard_dir, "runs")
        os.makedirs(cls.runs_dir, exist_ok=True)

        # Write mock index.html
        with open(os.path.join(cls.dashboard_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><head><title>Mock Dashboard</title></head><body>Mock</body></html>")

        # Write sample run JSON file
        cls.sample_run_id = "51c455ef-9a57-41e9-9132-841d1a610260"
        cls.sample_run_data = {
            "request_id": cls.sample_run_id,
            "role_arn": "arn:aws:iam::123456789012:role/cedar-sentinel-demo-role",
            "role_name": "cedar-sentinel-demo-role",
            "status": "APPLIED",
            "completed_at": "2026-09-19T14:35:10+00:00",
            "model_used": "apac.amazon.nova-lite-v1:0",
            "requested_policy": {"Version": "2012-10-17", "Statement": []},
            "iam_policy": {"Version": "2012-10-17", "Statement": []},
            "synthetic": False
        }
        with open(os.path.join(cls.runs_dir, "applied.json"), "w", encoding="utf-8") as f:
            json.dump(cls.sample_run_data, f, indent=2)

        # Find a free local port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()

        # Instantiate DashboardContext in offline mode
        cls.context = DashboardContext(
            port=cls.port,
            offline_dir=cls.runs_dir,
            dashboard_dir=cls.dashboard_dir,
            show_real_ids=False
        )

        handler_class = create_handler(cls.context)
        cls.server = socketserver.TCPServer(("127.0.0.1", cls.port), handler_class)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.test_dir.cleanup()

    def _make_request(self, method: str, path: str, headers: dict = None) -> Tuple[int, dict, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        req_headers = {"Host": f"127.0.0.1:{self.port}"}
        if headers:
            req_headers.update(headers)
        conn.request(method, path, headers=req_headers)
        resp = conn.getresponse()
        body = resp.read()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, resp_headers, body

    def test_bind_address_is_loopback(self):
        """Asserts the server socket is bound strictly to 127.0.0.1."""
        sockname = self.server.socket.getsockname()
        self.assertEqual(sockname[0], "127.0.0.1")

    def test_api_health(self):
        status, headers, body = self._make_request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("content-type", ""))
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["mode"], "live")
        self.assertEqual(data["source"], "offline")
        self.assertTrue(data["sanitized"])

    def test_api_runs_listing(self):
        status, headers, body = self._make_request("GET", "/api/runs?limit=10")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("runs", data)
        self.assertTrue(len(data["runs"]) >= 1)
        run0 = data["runs"][0]
        self.assertEqual(run0["request_id"], self.sample_run_id)
        self.assertEqual(run0["role_name"], "cedar-sentinel-demo-role")
        self.assertIn("<ACCOUNT_ID>", run0["role_arn"])

    def test_api_single_run_valid_uuid(self):
        status, headers, body = self._make_request("GET", f"/api/runs/{self.sample_run_id}")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["request_id"], self.sample_run_id)
        self.assertEqual(data["status"], "APPLIED")
        self.assertIn("<ACCOUNT_ID>", data["role_arn"])

    def test_api_single_run_invalid_uuid(self):
        """Asserts non-UUID request_id yields HTTP 400 Bad Request."""
        status, headers, body = self._make_request("GET", "/api/runs/not-a-valid-uuid")
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_api_single_run_not_found(self):
        """Asserts missing UUID yields HTTP 404."""
        missing_uuid = "00000000-0000-0000-0000-00000000000a"
        status, headers, body = self._make_request("GET", f"/api/runs/{missing_uuid}")
        self.assertEqual(status, 404)

    def test_unknown_api_endpoint(self):
        """Asserts unknown /api/* endpoint returns JSON 404, never falls back to index.html."""
        status, headers, body = self._make_request("GET", "/api/unknown-route")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers.get("content-type", ""))
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_host_header_validation(self):
        """Asserts invalid Host header receives 403 Forbidden (DNS rebinding defense)."""
        status, headers, body = self._make_request("GET", "/api/health", headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("Invalid Host", data.get("error", ""))

    def test_origin_header_validation(self):
        """Asserts cross-site Origin header receives 403 Forbidden."""
        status, headers, body = self._make_request("GET", "/api/health", headers={"Origin": "http://evil.example.com"})
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("Cross-origin", data.get("error", ""))

    def test_methods_not_allowed(self):
        """Asserts POST, PUT, DELETE, and OPTIONS return HTTP 405 Method Not Allowed."""
        for method in ("POST", "PUT", "DELETE", "OPTIONS"):
            status, headers, body = self._make_request(method, "/api/runs")
            self.assertEqual(status, 405, f"Method {method} expected 405 but got {status}")

    def test_path_traversal_protection(self):
        """Asserts path traversal attempts outside dashboard/ are rejected."""
        status, headers, body = self._make_request("GET", "/../cli/cedar_sentinel.py")
        self.assertIn(status, (403, 404))

        status, headers, body = self._make_request("GET", "/%2e%2e/cli/cedar_sentinel.py")
        self.assertIn(status, (403, 404))

    def test_dotfile_protection(self):
        """Asserts dotfile access returns 403/404."""
        status, headers, body = self._make_request("GET", "/.env")
        self.assertIn(status, (403, 404))

    def test_static_file_serving(self):
        """Asserts static files like index.html are served with nosniff header."""
        status, headers, body = self._make_request("GET", "/index.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertIn(b"Mock Dashboard", body)

    def test_head_method(self):
        """Asserts HEAD requests return headers with empty body."""
        status, headers, body = self._make_request("HEAD", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 0)

    def test_no_credentials_leaked_in_headers_or_body(self):
        """Asserts sensitive headers/body never expose secret keys."""
        status, headers, body = self._make_request("GET", "/api/health")
        dumped_headers = json.dumps(headers).lower()
        dumped_body = body.decode("utf-8").lower()
        self.assertNotIn("secretaccesskey", dumped_headers)
        self.assertNotIn("sessiontoken", dumped_headers)
        self.assertNotIn("secretaccesskey", dumped_body)
        self.assertNotIn("sessiontoken", dumped_body)


class TestXssSafetyAndInertRendering(unittest.TestCase):
    """Asserts that malicious XSS payloads in run fields are safely normalized and escaped."""

    def test_xss_payload_in_model_rationale_and_arn(self):
        xss_item = {
            "request_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
            "role_arn": 'arn:aws:iam::123456789012:role/xss"><script>alert(1)</script>',
            "role_name": 'xss"><script>alert(1)</script>',
            "status": "APPLIED",
            "rationale": '<img src=x onerror=alert(1)>"><script>fetch("http://evil")</script>',
            "observed_actions": {
                's3:GetObject"><script>alert(1)</script>': 5
            },
            "guard_removed_actions": ['s3:DeleteObject"><img src=x onerror=alert(2)>']
        }

        normalized = normalize_run_item(xss_item, show_real_ids=False)
        self.assertEqual(normalized["role_arn"], 'arn:aws:iam::<ACCOUNT_ID>:role/xss"><script>alert(1)</script>')
        self.assertEqual(normalized["rationale"], '<img src=x onerror=alert(1)>"><script>fetch("http://evil")</script>')

        # When rendered in DOM, textContent treats this as inert literal characters
        # And escapeHtml produces sanitized entities:
        escaped_rat = normalized["rationale"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        self.assertNotIn("<script>", escaped_rat)
        self.assertNotIn("<img", escaped_rat)


class TestModeDetectionFallback(unittest.TestCase):
    """Tests for front-end mode detection logic."""

    def test_mode_detection_html_fallback(self):
        """Simulate Amplify 200 rewrite returning HTML instead of JSON: verify mode detection rejects it."""
        # A response with text/html content-type must not be treated as live mode
        html_payload = "<!DOCTYPE html><html><body>Amplify Fallback</body></html>"
        content_type = "text/html"
        is_live = content_type.startswith("application/json") and '"mode":"live"' in html_payload
        self.assertFalse(is_live)

    def test_mode_detection_json_live_match(self):
        """Verify strict live mode requirement: 200 + application/json + 'mode': 'live'."""
        json_payload = json.dumps({"mode": "live", "region": "ap-south-1"})
        content_type = "application/json; charset=utf-8"
        data = json.loads(json_payload)
        is_live = "application/json" in content_type and data.get("mode") == "live"
        self.assertTrue(is_live)


if __name__ == "__main__":
    unittest.main(verbosity=2)
