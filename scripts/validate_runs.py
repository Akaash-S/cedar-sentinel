#!/usr/bin/env python3
"""
Validation script for Cedar Sentinel dashboard runs.
Loads every file listed in dashboard/runs/index.json and verifies:
1. File exists and parses as valid JSON
2. Required keys are present or explicitly allowed missing for that status
3. Item status matches manifest status
4. Synthetic runs are marked synthetic: true with synthetic_note
5. Zero unredacted AWS account IDs (no 12-digit numbers, no arn:aws:iam::[0-9]{12})
6. Zero unredacted AVP policy store IDs or policy IDs
7. Zero unredacted CloudTrail log group account IDs
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

RUNS_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "runs")
MANIFEST_PATH = os.path.join(RUNS_DIR, "index.json")

# Core keys expected across runs (some may be absent in error or processing states)
BASE_REQUIRED_KEYS = {"request_id", "status"}


def check_secrets(data: Any, path: str = "") -> List[str]:
    """Recursively scans data structure for unredacted sensitive identifiers."""
    violations = []
    
    if isinstance(data, str):
        # Check for 12-digit AWS account numbers
        acc_match = re.search(r"\b\d{12}\b", data)
        if acc_match:
            violations.append(f"{path}: Contains unredacted 12-digit number '{acc_match.group(0)}'")

        # Check for ARN with unredacted digits
        arn_match = re.search(r"arn:aws:iam::\d+:", data)
        if arn_match:
            violations.append(f"{path}: Contains unredacted ARN '{arn_match.group(0)}'")

        # Check for unredacted CloudTrail log group
        lg_match = re.search(r"aws-cloudtrail-logs-\d{12}", data)
        if lg_match:
            violations.append(f"{path}: Contains unredacted log group '{lg_match.group(0)}'")

    elif isinstance(data, dict):
        for k, v in data.items():
            current_path = f"{path}.{k}" if path else k
            if k in ("policy_store_id", "policyStoreId") and isinstance(v, str) and v != "<AVP_STORE_ID>":
                violations.append(f"{current_path}: Unredacted policy_store_id '{v}'")
            if k in ("policy_id", "policyId") and isinstance(v, str) and v != "<POLICY_ID>":
                violations.append(f"{current_path}: Unredacted policy_id '{v}'")
            violations.extend(check_secrets(v, current_path))

    elif isinstance(data, list):
        for i, item in enumerate(data):
            violations.extend(check_secrets(item, f"{path}[{i}]"))

    return violations


def validate_all_runs(manifest_path: str = MANIFEST_PATH, runs_dir: str = RUNS_DIR) -> int:
    print(f"[1/4] Checking manifest file at: {manifest_path}")
    if not os.path.exists(manifest_path):
        print(f"FAIL: Manifest not found at {manifest_path}", file=sys.stderr)
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        try:
            manifest = json.load(f)
        except json.JSONDecodeError as e:
            print(f"FAIL: Manifest is invalid JSON: {e}", file=sys.stderr)
            return 1

    if not isinstance(manifest, list) or len(manifest) == 0:
        print(f"FAIL: Manifest must be a non-empty JSON list", file=sys.stderr)
        return 1

    print(f"  Manifest contains {len(manifest)} run entries.")

    errors = []
    print(f"[2/4] Validating individual run files against manifest and schemas...")

    for entry in manifest:
        run_id = entry.get("id")
        run_file = entry.get("file")
        expected_status = entry.get("status")
        is_synthetic = entry.get("synthetic", False)

        print(f"  - Validating '{run_id}' ({run_file})...")

        if not run_file:
            errors.append(f"Manifest entry '{run_id}' missing 'file' attribute")
            continue

        file_path = os.path.join(runs_dir, os.path.basename(run_file))
        if not os.path.exists(file_path):
            errors.append(f"Run file '{file_path}' does not exist on disk")
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as rf:
                run_data = json.load(rf)
        except json.JSONDecodeError as e:
            errors.append(f"Run file '{run_file}' is invalid JSON: {e}")
            continue

        # Check required base keys
        for rk in BASE_REQUIRED_KEYS:
            if rk not in run_data:
                errors.append(f"{run_file}: Missing required key '{rk}'")

        # Check status matches manifest
        actual_status = run_data.get("status")
        if actual_status != expected_status:
            errors.append(f"{run_file}: Status mismatch! Manifest says '{expected_status}', file has '{actual_status}'")

        # Check synthetic flags
        if is_synthetic:
            if not run_data.get("synthetic", False):
                errors.append(f"{run_file}: Marked synthetic in manifest but missing 'synthetic: true' in data")
            if not run_data.get("synthetic_note"):
                errors.append(f"{run_file}: Synthetic run missing 'synthetic_note'")
        else:
            if run_data.get("synthetic", False):
                errors.append(f"{run_file}: Marked real in manifest but has 'synthetic: true' in data")

        # Check for unredacted sensitive tokens
        secret_violations = check_secrets(run_data)
        if secret_violations:
            for sv in secret_violations:
                errors.append(f"{run_file}: {sv}")

    print(f"[3/4] Checking for orphaned files in {runs_dir}...")
    manifest_files = {os.path.basename(e.get("file", "")) for e in manifest}
    manifest_files.add("index.json")
    for fname in os.listdir(runs_dir):
        if fname.endswith(".json") and fname not in manifest_files:
            errors.append(f"Orphaned file '{fname}' in runs directory not referenced in manifest")

    print(f"[4/4] Summary & Results:")
    if errors:
        print(f"\n[FAIL] Found {len(errors)} validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"\n[SUCCESS] All {len(manifest)} runs in manifest are valid, well-formed, sanitized, and consistent!")
    return 0


if __name__ == "__main__":
    sys.exit(validate_all_runs())
