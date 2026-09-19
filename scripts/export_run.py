#!/usr/bin/env python3
"""
Export script for Cedar Sentinel dashboard.
Reads a completed/applied pipeline run from DynamoDB (cedar-sentinel-results),
sanitizes sensitive identifiers (account IDs, ARNs), and writes dashboard/run.json.
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict
import boto3
from botocore.exceptions import ClientError

DEFAULT_TABLE_NAME = "cedar-sentinel-results"
DEFAULT_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "dashboard", "run.json")


def sanitize_value(val: Any) -> Any:
    """Recursively replaces AWS account IDs, policy store IDs, and sensitive paths."""
    if isinstance(val, str):
        # Replace 12-digit AWS account ID with placeholder
        sanitized = re.sub(r"\b\d{12}\b", "<ACCOUNT_ID>", val)
        # Redact 22-character alphanumeric AVP store IDs
        sanitized = re.sub(r"\b[A-Za-z0-9]{22}\b", "<AVP_STORE_ID>", sanitized)
        return sanitized
    elif isinstance(val, dict):
        return {k: sanitize_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_value(v) for v in val]
    return val


def export_run(request_id: str, table_name: str, output_path: str, region: str) -> int:
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)

    print(f"Fetching run '{request_id}' from DynamoDB table '{table_name}'...")
    try:
        resp = table.get_item(Key={"request_id": request_id})
        item = resp.get("Item")
        if not item:
            print(f"Error: Item with request_id '{request_id}' not found.", file=sys.stderr)
            return 1
    except ClientError as err:
        print(f"Error reading DynamoDB: {err}", file=sys.stderr)
        return 1

    # Convert DynamoDB Decimal objects to int/float/str
    def decimal_default(obj):
        import decimal
        if isinstance(obj, decimal.Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        raise TypeError

    raw_json = json.loads(json.dumps(item, default=decimal_default))
    sanitized_item = sanitize_value(raw_json)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sanitized_item, f, indent=2)

    print(f"[SUCCESS] Exported and sanitized run data to '{output_path}'.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Export sanitized Cedar Sentinel run to dashboard/run.json")
    parser.add_argument("request_id", help="DynamoDB request_id of the run to export")
    parser.add_argument("--table", default=DEFAULT_TABLE_NAME, help=f"DynamoDB table name (default: {DEFAULT_TABLE_NAME})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help=f"Output path (default: {DEFAULT_OUTPUT_PATH})")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-south-1"), help="AWS region")
    args = parser.parse_args()

    sys.exit(export_run(args.request_id, args.table, args.output, args.region))


if __name__ == "__main__":
    main()
