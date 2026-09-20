"""
Local Live Dashboard Server for Cedar Sentinel.
Runs on 127.0.0.1, read-only, using the developer's local AWS credentials.
"""

import argparse
import http.server
import json
import mimetypes
import os
import re
import socketserver
import sys
import urllib.parse
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from cli.run_data import decimal_default, normalize_run_item, sanitize_value

DEFAULT_PORT = 8765
DEFAULT_TABLE_NAME = "cedar-sentinel-results"
DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard"))
UUID_REGEX = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class DashboardContext:
    """Holds configuration and client state for the local dashboard server."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        region: Optional[str] = None,
        table_name: str = DEFAULT_TABLE_NAME,
        profile: Optional[str] = None,
        show_real_ids: bool = False,
        offline_dir: Optional[str] = None,
        dashboard_dir: str = DASHBOARD_DIR,
    ):
        self.port = port
        self.region = region or os.environ.get("AWS_REGION", "ap-south-1")
        self.table_name = table_name
        self.profile = profile
        self.show_real_ids = show_real_ids
        self.offline_dir = os.path.abspath(offline_dir) if offline_dir else None
        self.dashboard_dir = os.path.abspath(dashboard_dir)

        self.session = None
        self.sts_client = None
        self.dynamodb_resource = None
        self.table = None
        self.caller_arn = "offline"
        self.caller_name = "offline"
        self.account_id = "<ACCOUNT_ID>"

        if not self.offline_dir:
            self._init_aws()

    def _init_aws(self) -> None:
        """Initializes boto3 session and clients."""
        try:
            if self.profile:
                self.session = boto3.Session(profile_name=self.profile, region_name=self.region)
            else:
                self.session = boto3.Session(region_name=self.region)

            self.sts_client = self.session.client("sts")
            identity = self.sts_client.get_caller_identity()
            self.caller_arn = identity.get("Arn", "")
            self.account_id = identity.get("Account", "")
            self.caller_name = self.caller_arn.split("/")[-1] if "/" in self.caller_arn else self.caller_arn

            self.dynamodb_resource = self.session.resource("dynamodb")
            self.table = self.dynamodb_resource.Table(self.table_name)
            # Lightweight check: verify table can be described/accessed
            self.table.load()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            msg = exc.response.get("Error", {}).get("Message", str(exc))
            print(f"\n[ERROR] AWS initialization failed: [{code}] {msg}", file=sys.stderr)
            print(f"Please check your AWS credentials (e.g. `aws sts get-caller-identity`).", file=sys.stderr)
            print(f"Required IAM permissions: dynamodb:GetItem, dynamodb:Scan on '{self.table_name}', and sts:GetCallerIdentity.", file=sys.stderr)
            sys.exit(1)
        except BotoCoreError as exc:
            print(f"\n[ERROR] AWS credential error: {exc}", file=sys.stderr)
            print("Run `aws sts get-caller-identity` to verify active credentials.", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"\n[ERROR] Failed to connect to AWS: {exc}", file=sys.stderr)
            sys.exit(1)

    def get_masked_identity(self) -> str:
        if self.offline_dir:
            return "offline-user"
        if self.show_real_ids:
            return self.caller_arn
        # Mask account ID in ARN
        masked = re.sub(r":\d{12}:", ":<ACCOUNT_ID>:", self.caller_arn)
        return masked


def create_handler(context: DashboardContext):
    """Factory to create LocalDashboardRequestHandler bound to a DashboardContext."""

    class LocalDashboardRequestHandler(http.server.BaseHTTPRequestHandler):
        server_version = "CedarSentinelDashboard/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            """Quiet logging: log method, path and status only. Never log bodies, ARNs, credentials."""
            sys.stderr.write(f"[127.0.0.1] {self.command} {self.path} -> {args[1] if len(args) > 1 else args[0]}\n")

        def _send_json(self, status_code: int, data: Any) -> None:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status_code: int, message: str) -> None:
            self._send_json(status_code, {"error": message, "status": status_code})

        def _validate_host_and_origin(self) -> bool:
            """Validates Host and Origin headers to defend against DNS rebinding & CSRF."""
            host_header = self.headers.get("Host", "").strip().lower()
            allowed_hosts = {
                f"127.0.0.1:{context.port}",
                f"localhost:{context.port}",
                "127.0.0.1",
                "localhost",
            }
            if host_header not in allowed_hosts:
                self._send_error_json(403, "Forbidden: Invalid Host header")
                return False

            origin_header = self.headers.get("Origin")
            if origin_header:
                origin_clean = origin_header.strip().lower()
                allowed_origins = {
                    f"http://127.0.0.1:{context.port}",
                    f"http://localhost:{context.port}",
                    "http://127.0.0.1",
                    "http://localhost",
                }
                if origin_clean not in allowed_origins:
                    self._send_error_json(403, "Forbidden: Cross-origin requests not allowed")
                    return False

            return True

        def do_HEAD(self) -> None:
            if not self._validate_host_and_origin():
                return
            self._handle_request(head_only=True)

        def do_GET(self) -> None:
            if not self._validate_host_and_origin():
                return
            self._handle_request(head_only=False)

        def do_POST(self) -> None:
            self._send_error_json(405, "Method Not Allowed")

        def do_PUT(self) -> None:
            self._send_error_json(405, "Method Not Allowed")

        def do_DELETE(self) -> None:
            self._send_error_json(405, "Method Not Allowed")

        def do_OPTIONS(self) -> None:
            self._send_error_json(405, "Method Not Allowed")

        def _handle_request(self, head_only: bool = False) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            # Route API endpoints
            if path == "/api/health":
                self._handle_api_health()
                return

            if path == "/api/runs":
                limit_param = query.get("limit", ["50"])[0]
                try:
                    limit = min(max(int(limit_param), 1), 200)
                except ValueError:
                    limit = 50
                self._handle_api_runs(limit=limit)
                return

            if path.startswith("/api/runs/"):
                request_id = path[len("/api/runs/") :].strip("/")
                self._handle_api_single_run(request_id)
                return

            if path.startswith("/api/"):
                self._send_error_json(404, f"Unknown API endpoint: {path}")
                return

            # Route Static files under dashboard/
            self._handle_static_file(path, head_only=head_only)

        def _handle_api_health(self) -> None:
            health_data = {
                "mode": "live",
                "source": "offline" if context.offline_dir else "aws",
                "region": context.region,
                "table": context.table_name if not context.offline_dir else "offline",
                "identity": context.get_masked_identity(),
                "sanitized": not context.show_real_ids,
            }
            self._send_json(200, health_data)

        def _handle_api_runs(self, limit: int = 50) -> None:
            if context.offline_dir:
                self._handle_api_runs_offline(limit=limit)
            else:
                self._handle_api_runs_aws(limit=limit)

        def _handle_api_runs_offline(self, limit: int) -> None:
            runs_list = []
            if os.path.exists(context.offline_dir):
                for fname in os.listdir(context.offline_dir):
                    if fname.endswith(".json") and fname != "index.json":
                        fpath = os.path.join(context.offline_dir, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            role_arn = data.get("role_arn", "")
                            if not context.show_real_ids:
                                role_arn = sanitize_value(role_arn, show_real_ids=False)
                            role_name = role_arn.split("/")[-1] if "/" in role_arn else role_arn.split(":")[-1]
                            runs_list.append(
                                {
                                    "request_id": data.get("request_id", fname.replace(".json", "")),
                                    "role_arn": role_arn,
                                    "role_name": role_name,
                                    "status": data.get("status", "UNKNOWN"),
                                    "completed_at": data.get("completed_at") or data.get("created_at") or "",
                                    "model_used": data.get("model_used", ""),
                                }
                            )
                        except Exception:
                            pass

            def sort_key(x: Dict[str, Any]) -> Tuple[int, str]:
                is_processing = 0 if x.get("status") == "PROCESSING" else 1
                return (is_processing, str(x.get("completed_at", "")))

            runs_list.sort(key=sort_key, reverse=False)
            # Reverse only time within the same processing priority
            proc_runs = [r for r in runs_list if r.get("status") == "PROCESSING"]
            done_runs = [r for r in runs_list if r.get("status") != "PROCESSING"]
            done_runs.sort(key=lambda r: str(r.get("completed_at", "")), reverse=True)
            sorted_runs = (proc_runs + done_runs)[:limit]

            self._send_json(200, {"runs": sorted_runs})

        def _handle_api_runs_aws(self, limit: int) -> None:
            items = []
            try:
                # Use projection expression. '#s' for reserved keyword 'status'
                proj_expr = "request_id, role_arn, role_name, #s, completed_at, created_at, model_used"
                expr_names = {"#s": "status"}

                paginator_count = 0
                max_pages = 5
                scan_kwargs = {
                    "ProjectionExpression": proj_expr,
                    "ExpressionAttributeNames": expr_names,
                    "Limit": limit,
                }

                while paginator_count < max_pages:
                    resp = context.table.scan(**scan_kwargs)
                    raw_items = resp.get("Items", [])
                    items.extend(raw_items)
                    paginator_count += 1
                    last_key = resp.get("LastEvaluatedKey")
                    if not last_key or len(items) >= limit:
                        break
                    scan_kwargs["ExclusiveStartKey"] = last_key

            except (BotoCoreError, ClientError) as exc:
                self._send_error_json(500, f"DynamoDB Scan failed: {exc}")
                return

            runs_list = []
            for item in items:
                raw_json = json.loads(json.dumps(item, default=decimal_default))
                req_id = raw_json.get("request_id", "")
                role_arn = raw_json.get("role_arn", "")
                if not context.show_real_ids:
                    role_arn = sanitize_value(role_arn, show_real_ids=False)
                role_name = raw_json.get("role_name") or (role_arn.split("/")[-1] if "/" in role_arn else role_arn.split(":")[-1])
                status = raw_json.get("status", "UNKNOWN")
                completed_at = raw_json.get("completed_at") or raw_json.get("created_at") or ""
                model_used = raw_json.get("model_used", "")

                runs_list.append(
                    {
                        "request_id": req_id,
                        "role_arn": role_arn,
                        "role_name": role_name,
                        "status": status,
                        "completed_at": completed_at,
                        "model_used": model_used,
                    }
                )

            # Sort: PROCESSING items first, then newest completed_at first
            proc_runs = [r for r in runs_list if r.get("status") == "PROCESSING"]
            done_runs = [r for r in runs_list if r.get("status") != "PROCESSING"]
            done_runs.sort(key=lambda r: str(r.get("completed_at", "")), reverse=True)
            sorted_runs = (proc_runs + done_runs)[:limit]

            self._send_json(200, {"runs": sorted_runs})

        def _handle_api_single_run(self, request_id: str) -> None:
            # Validate strict UUID format
            if not UUID_REGEX.match(request_id):
                self._send_error_json(400, f"Invalid request_id format: '{request_id}' must be a valid UUID")
                return

            if context.offline_dir:
                self._handle_api_single_run_offline(request_id)
            else:
                self._handle_api_single_run_aws(request_id)

        def _handle_api_single_run_offline(self, request_id: str) -> None:
            if not os.path.exists(context.offline_dir):
                self._send_error_json(404, f"Run '{request_id}' not found in offline directory")
                return

            # Search in offline dir
            found_data = None
            for fname in os.listdir(context.offline_dir):
                if fname.endswith(".json") and fname != "index.json":
                    fpath = os.path.join(context.offline_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("request_id") == request_id or fname.replace(".json", "") == request_id:
                            found_data = data
                            break
                    except Exception:
                        pass

            if not found_data:
                self._send_error_json(404, f"Run '{request_id}' not found")
                return

            normalized = normalize_run_item(found_data, show_real_ids=context.show_real_ids)
            self._send_json(200, normalized)

        def _handle_api_single_run_aws(self, request_id: str) -> None:
            try:
                resp = context.table.get_item(Key={"request_id": request_id})
                item = resp.get("Item")
                if not item:
                    self._send_error_json(404, f"Run '{request_id}' not found")
                    return
            except (BotoCoreError, ClientError) as exc:
                self._send_error_json(500, f"DynamoDB GetItem failed: {exc}")
                return

            normalized = normalize_run_item(item, show_real_ids=context.show_real_ids)
            self._send_json(200, normalized)

        def _handle_static_file(self, rel_path: str, head_only: bool = False) -> None:
            # Normalize path and default '/' to '/index.html'
            clean_path = rel_path.lstrip("/")
            if not clean_path:
                clean_path = "index.html"

            # Traversal check: resolve path and ensure it starts with dashboard_dir
            resolved_path = os.path.abspath(os.path.join(context.dashboard_dir, clean_path))
            try:
                common = os.path.commonpath([context.dashboard_dir, resolved_path])
            except ValueError:
                self._send_error_json(403, "Forbidden: Path traversal")
                return

            if common != context.dashboard_dir:
                self._send_error_json(403, "Forbidden: Path traversal")
                return

            # Check dotfiles
            parts = clean_path.split("/")
            if any(p.startswith(".") for p in parts if p):
                self._send_error_json(403, "Forbidden: Hidden file access")
                return

            # Check existence and file type (no directory listing)
            if not os.path.exists(resolved_path) or os.path.isdir(resolved_path):
                self._send_error_json(404, "File Not Found")
                return

            content_type, _ = mimetypes.guess_type(resolved_path)
            if content_type is None:
                content_type = "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                content_type += "; charset=utf-8"

            try:
                with open(resolved_path, "rb") as f:
                    content = f.read()

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()

                if not head_only:
                    self.wfile.write(content)
            except Exception as exc:
                self._send_error_json(500, f"Failed reading file: {exc}")

    return LocalDashboardRequestHandler


def start_dashboard_server(
    port: int = DEFAULT_PORT,
    region: Optional[str] = None,
    table_name: str = DEFAULT_TABLE_NAME,
    profile: Optional[str] = None,
    run_id: Optional[str] = None,
    no_open: bool = False,
    show_real_ids: bool = False,
    offline_dir: Optional[str] = None,
) -> None:
    """Starts the local dashboard HTTP server."""
    context = DashboardContext(
        port=port,
        region=region,
        table_name=table_name,
        profile=profile,
        show_real_ids=show_real_ids,
        offline_dir=offline_dir,
    )

    handler_class = create_handler(context)

    # Server binding to 127.0.0.1 ONLY
    server_address = ("127.0.0.1", port)

    try:
        class LocalHTTPServer(socketserver.TCPServer):
            allow_reuse_address = False

        httpd = LocalHTTPServer(server_address, handler_class)
    except OSError as exc:
        print(f"\n[ERROR] Could not bind to 127.0.0.1:{port}: {exc}", file=sys.stderr)
        print(f"Port {port} may be in use by another process. Specify another port with --port.", file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    if run_id:
        url += f"/?run={urllib.parse.quote(run_id)}"

    print("=" * 65)
    print("  Cedar Sentinel — Local Live Dashboard Server")
    print("=" * 65)
    if offline_dir:
        print(f"  [OFFLINE MODE] Reading run files from: {offline_dir}")
    else:
        print(f"  Connected as : {context.get_masked_identity()}")
        print(f"  Region       : {context.region}")
        print(f"  Table        : {context.table_name}")

    if show_real_ids:
        print("  [WARNING] --show-real-ids is ON: real ARNs and account IDs will be visible. Do not screen-record.")
    else:
        print("  Sanitization : ON (account IDs & ARNs masked)")

    print(f"  Local URL    : {url}")
    print("=" * 65)
    print("Press Ctrl-C to shut down cleanly.\n")

    if not no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down local dashboard server...")
    finally:
        httpd.server_close()
        print("Server stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Cedar Sentinel local dashboard server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind to on 127.0.0.1 (default: {DEFAULT_PORT})")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"), help="AWS region")
    parser.add_argument("--table", default=DEFAULT_TABLE_NAME, help=f"DynamoDB results table name (default: {DEFAULT_TABLE_NAME})")
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"), help="AWS CLI profile name")
    parser.add_argument("--run", dest="run_id", help="Deep link to specific run request_id on open")
    parser.add_argument("--no-open", action="store_true", help="Do not automatically open the browser on startup")
    parser.add_argument("--show-real-ids", action="store_true", help="Do not sanitize/mask real AWS account IDs and ARNs")
    parser.add_argument("--offline-dir", help="Serve runs from local directory instead of connecting to AWS")

    args = parser.parse_args()
    start_dashboard_server(
        port=args.port,
        region=args.region,
        table_name=args.table,
        profile=args.profile,
        run_id=args.run_id,
        no_open=args.no_open,
        show_real_ids=args.show_real_ids,
        offline_dir=args.offline_dir,
    )


if __name__ == "__main__":
    main()
