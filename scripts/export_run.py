#!/usr/bin/env python3
"""
Export and sanitization script for Cedar Sentinel dashboard.
Reads completed/applied pipeline runs from DynamoDB (cedar-sentinel-results),
sanitizes sensitive identifiers (account IDs, ARNs, policy stores, log groups),
and writes structured JSON files to dashboard/runs/.
Also generates dashboard/runs/index.json and supports synthetic run generation and unit testing.
"""

import argparse
import decimal
import json
import os
import re
import sys
import unittest
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

DEFAULT_TABLE_NAME = "cedar-sentinel-results"
RUNS_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "runs")
MANIFEST_PATH = os.path.join(RUNS_DIR, "index.json")


def sanitize_value(val: Any) -> Any:
    """
    Recursively replaces sensitive AWS identifiers:
    - 12-digit AWS account IDs -> <ACCOUNT_ID>
    - Role/User ARNs keep role name but use <ACCOUNT_ID>
    - AVP policy store IDs (e.g. 22-char alphanumeric) -> <AVP_STORE_ID>
    - AVP policy IDs -> <POLICY_ID>
    - CloudTrail log group names (e.g. aws-cloudtrail-logs-...) -> <LOG_GROUP>
    - Removes 'ttl' field
    - Parses JSON-encoded strings (requested_policy, previous_policy, iam_policy)
    - Coerces observed_actions counts to integers
    """
    if isinstance(val, str):
        # 1. Check if string is a JSON object/array that should be parsed
        s_stripped = val.strip()
        if (s_stripped.startswith("{") and s_stripped.endswith("}")) or (s_stripped.startswith("[") and s_stripped.endswith("]")):
            try:
                parsed = json.loads(s_stripped)
                # If parsed is a dict/list, sanitize it recursively
                return sanitize_value(parsed)
            except Exception:
                pass

        # 2. CloudTrail log groups
        sanitized = re.sub(r"aws-cloudtrail-logs-[a-zA-Z0-9_-]+", "<LOG_GROUP>", val)
        # 3. Specific ARN replacements: keep resource name, replace account ID
        sanitized = re.sub(r"arn:aws:([a-zA-Z0-9-]+):([a-zA-Z0-9-]*):(\d{12}):", r"arn:aws:\1:\2:<ACCOUNT_ID>:", sanitized)
        # 4. Any remaining 12-digit account IDs
        sanitized = re.sub(r"\b\d{12}\b", "<ACCOUNT_ID>", sanitized)
        # 5. AVP policy store IDs (e.g. 22 chars base62 alphanumeric)
        sanitized = re.sub(r"\b[A-Za-z0-9]{22}\b", "<AVP_STORE_ID>", sanitized)
        return sanitized

    elif isinstance(val, dict):
        sanitized_dict = {}
        for k, v in val.items():
            if k == "ttl":
                continue
            
            # If observed_actions, coerce count strings to ints
            if k == "observed_actions" and isinstance(v, dict):
                sanitized_obs = {}
                for act_name, count_val in v.items():
                    try:
                        sanitized_obs[sanitize_value(act_name)] = int(count_val)
                    except (ValueError, TypeError):
                        sanitized_obs[sanitize_value(act_name)] = count_val
                sanitized_dict[k] = sanitized_obs
                continue

            # If coverage_check.blocked_actions is a JSON string, parse it
            if k == "coverage_check" and isinstance(v, dict):
                cov_dict = dict(v)
                if "blocked_actions" in cov_dict and isinstance(cov_dict["blocked_actions"], str):
                    try:
                        cov_dict["blocked_actions"] = json.loads(cov_dict["blocked_actions"])
                    except Exception:
                        pass
                sanitized_dict[k] = sanitize_value(cov_dict)
                continue

            # If policy_id or policy_store_id fields
            if k in ("policy_id", "policyId") and isinstance(v, str):
                sanitized_dict[k] = "<POLICY_ID>"
                continue
            if k in ("policy_store_id", "policyStoreId") and isinstance(v, str):
                sanitized_dict[k] = "<AVP_STORE_ID>"
                continue

            sanitized_dict[k] = sanitize_value(v)
        return sanitized_dict

    elif isinstance(val, list):
        return [sanitize_value(v) for v in val]

    elif isinstance(val, decimal.Decimal):
        return int(val) if val % 1 == 0 else float(val)

    return val


def decimal_default(obj: Any) -> Any:
    if isinstance(obj, decimal.Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def scan_dynamodb_runs(table_name: str, region: str) -> List[Dict[str, Any]]:
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    print(f"Scanning DynamoDB table '{table_name}' in region '{region}'...")
    try:
        resp = table.scan()
        items = resp.get("Items", [])
        clean_items = [json.loads(json.dumps(item, default=decimal_default)) for item in items]
        return clean_items
    except ClientError as err:
        print(f"Error scanning DynamoDB: {err}", file=sys.stderr)
        return []


def export_single_run(request_id: str, table_name: str, output_path: str, region: str, label: Optional[str] = None) -> Dict[str, Any]:
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)

    print(f"Fetching run '{request_id}' from DynamoDB...")
    try:
        resp = table.get_item(Key={"request_id": request_id})
        item = resp.get("Item")
        if not item:
            raise ValueError(f"Item with request_id '{request_id}' not found.")
    except ClientError as err:
        raise RuntimeError(f"DynamoDB error: {err}")

    raw_json = json.loads(json.dumps(item, default=decimal_default))
    sanitized_item = sanitize_value(raw_json)
    sanitized_item["synthetic"] = False

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sanitized_item, f, indent=2)

    print(f"[SUCCESS] Exported {request_id} -> {output_path}")
    return sanitized_item


def create_synthetic_run(from_file: str, output_path: str, set_fields: Dict[str, Any], note: str, label: str) -> Dict[str, Any]:
    with open(from_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["synthetic"] = True
    data["synthetic_note"] = note
    for k, v in set_fields.items():
        # handle nested keys like coverage_check.passed
        if "." in k:
            parts = k.split(".")
            curr = data
            for p in parts[:-1]:
                if p not in curr:
                    curr[p] = {}
                curr = curr[p]
            curr[parts[-1]] = v
        else:
            data[k] = v

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[SUCCESS] Created synthetic run from {from_file} -> {output_path}")
    return data


def regenerate_manifest(runs_dir: str = RUNS_DIR, manifest_path: str = MANIFEST_PATH) -> List[Dict[str, Any]]:
    """Scans runs_dir and writes index.json."""
    if not os.path.exists(runs_dir):
        return []

    # Manifest metadata config map by file basename
    metadata_map = {
        "applied.json": {
            "id": "applied",
            "label": "APPLIED — guard removed 11 unobserved actions",
            "file": "runs/applied.json"
        },
        "declined.json": {
            "id": "declined",
            "label": "DECLINED — developer rejected the diff",
            "file": "runs/declined.json"
        },
        "analyzer_invalid.json": {
            "id": "analyzer_invalid",
            "label": "ANALYZER_INVALID — CheckNoNewAccess failed",
            "file": "runs/analyzer_invalid.json"
        },
        "blocked.json": {
            "id": "blocked",
            "label": "BLOCKED — coverage check dropped observed action",
            "file": "runs/blocked.json"
        },
        "cedar_invalid.json": {
            "id": "cedar_invalid",
            "label": "CEDAR_INVALID — syntax / schema error in draft",
            "file": "runs/cedar_invalid.json"
        },
        "complete.json": {
            "id": "complete",
            "label": "COMPLETE — verified, awaiting review",
            "file": "runs/complete.json"
        },
        "error.json": {
            "id": "error",
            "label": "ERROR — unhandled pipeline exception",
            "file": "runs/error.json"
        },
        "applied_unverified.json": {
            "id": "applied_unverified",
            "label": "APPLIED_UNVERIFIED — put succeeded, read-back failed",
            "file": "runs/applied_unverified.json"
        },
        "apply_failed.json": {
            "id": "apply_failed",
            "label": "APPLY_FAILED — IAM PutRolePolicy returned error",
            "file": "runs/apply_failed.json"
        },
        "processing.json": {
            "id": "processing",
            "label": "PROCESSING — run still in progress",
            "file": "runs/processing.json"
        }
    }

    manifest = []
    # Preferred order of display
    ordered_files = [
        "applied.json",
        "complete.json",
        "declined.json",
        "analyzer_invalid.json",
        "cedar_invalid.json",
        "blocked.json",
        "applied_unverified.json",
        "apply_failed.json",
        "error.json",
        "processing.json"
    ]

    for fname in ordered_files:
        fpath = os.path.join(runs_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            meta = metadata_map.get(fname, {
                "id": fname.replace(".json", ""),
                "label": f"{data.get('status', 'UNKNOWN')} — {fname}",
                "file": f"runs/{fname}"
            })

            entry = {
                "id": meta["id"],
                "label": meta["label"],
                "file": meta["file"],
                "status": data.get("status", "UNKNOWN"),
                "synthetic": data.get("synthetic", False),
                "source_request_id": data.get("request_id", ""),
                "captured_at": data.get("completed_at") or data.get("created_at") or "2026-09-19T14:34:49+00:00"
            }
            manifest.append(entry)
        except Exception as e:
            print(f"Warning: Failed reading {fname}: {e}", file=sys.stderr)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[SUCCESS] Wrote manifest ({len(manifest)} runs) -> {manifest_path}")
    return manifest


class TestSanitizer(unittest.TestCase):
    """Unit tests for sanitization logic."""

    def test_account_id_and_arn_sanitization(self):
        fake_item = {
            "request_id": "test-123",
            "role_arn": "arn:aws:iam::123456789012:role/cedar-sentinel-demo-role",
            "log_group": "aws-cloudtrail-logs-testgroup",
            "policy_store_id": "ABCDefgh1234567890WXYZ",
            "policy_id": "POL_987654321012345678",
            "ttl": 1726750000,
            "observed_actions": {
                "s3:GetObject": "14",
                "s3:PutObject": 5
            },
            "requested_policy": "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:*\",\"Resource\":\"*\"}]}"
        }

        sanitized = sanitize_value(fake_item)

        # Assert 12-digit account ID removed
        self.assertEqual(sanitized["role_arn"], "arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role")
        self.assertEqual(sanitized["log_group"], "<LOG_GROUP>")
        self.assertEqual(sanitized["policy_store_id"], "<AVP_STORE_ID>")
        self.assertEqual(sanitized["policy_id"], "<POLICY_ID>")
        # Assert TTL removed
        self.assertNotIn("ttl", sanitized)
        # Assert counts coerced to int
        self.assertEqual(sanitized["observed_actions"]["s3:GetObject"], 14)
        self.assertEqual(sanitized["observed_actions"]["s3:PutObject"], 5)
        # Assert JSON string parsed
        self.assertIsInstance(sanitized["requested_policy"], dict)
        self.assertEqual(sanitized["requested_policy"]["Statement"][0]["Action"], "s3:*")
        # Assert no 12-digit number remains
        dumped = json.dumps(sanitized)
        self.assertFalse(bool(re.search(r"\b123456789012\b", dumped)))


def run_unit_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSanitizer)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Export sanitized Cedar Sentinel runs for dashboard.")
    parser.add_argument("--scan", action="store_true", help="Scan DynamoDB results table and list available runs")
    parser.add_argument("--request-id", help="DynamoDB request_id of the run to export")
    parser.add_argument("--out", help="Output file path (e.g. dashboard/runs/applied.json)")
    parser.add_argument("--label", help="Descriptive label for manifest")
    parser.add_argument("--synthetic", action="store_true", help="Create a synthetic / crafted run")
    parser.add_argument("--from-file", dest="from_file", help="Source JSON file to base synthetic run on")
    parser.add_argument("--set", dest="set_fields", nargs="*", default=[], help="Key=value overrides for synthetic run")
    parser.add_argument("--note", help="Synthetic note explanation")
    parser.add_argument("--generate-manifest", action="store_true", help="Regenerate dashboard/runs/index.json")
    parser.add_argument("--test", action="store_true", help="Run sanitizer unit tests")
    parser.add_argument("--table", default=DEFAULT_TABLE_NAME, help=f"DynamoDB table name (default: {DEFAULT_TABLE_NAME})")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-south-1"), help="AWS region")

    args = parser.parse_args()

    if args.test:
        sys.exit(run_unit_tests())

    if args.scan:
        items = scan_dynamodb_runs(args.table, args.region)
        print(f"\n--- DynamoDB Runs in {args.table} ({len(items)} items) ---")
        for it in sorted(items, key=lambda x: str(x.get("completed_at", ""))):
            req_id = it.get("request_id")
            status = it.get("status")
            comp = it.get("completed_at") or it.get("created_at")
            guard_rem = len(it.get("guard_removed_actions", [])) if isinstance(it.get("guard_removed_actions"), list) else 0
            model = it.get("model_used", "")
            print(f"Request ID: {req_id} | Status: {status:<18} | Completed: {comp} | Guard removed: {guard_rem} | Model: {model}")
        return

    if args.synthetic:
        if not args.from_file or not args.out:
            print("Error: --synthetic requires --from-file, --out, and --note", file=sys.stderr)
            sys.exit(1)
        overrides = {}
        for s in args.set_fields:
            if "=" in s:
                k, v = s.split("=", 1)
                # coerce json values if boolean/number/dict
                try:
                    v = json.loads(v)
                except Exception:
                    pass
                overrides[k] = v
        create_synthetic_run(args.from_file, args.out, overrides, args.note or "Crafted synthetic run for dashboard demonstration.", args.label or "")
        regenerate_manifest()
        return

    if args.request_id and args.out:
        export_single_run(args.request_id, args.table, args.out, args.region, args.label)
        regenerate_manifest()
        return

    if args.generate_manifest:
        regenerate_manifest()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
