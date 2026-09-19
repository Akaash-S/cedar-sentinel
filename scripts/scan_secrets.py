#!/usr/bin/env python3
"""
Pre-push security and redaction scanner.
Scans responses, docs, dashboard, and source files for unredacted:
- 12-digit AWS account IDs
- AVP Policy Store IDs
- AVP Policy IDs
- CloudTrail log group names with account IDs
"""

import os
import re
import sys

IGNORE_FILES = {
    "samconfig.toml",
    ".aws-sam",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "template.yaml",
    ".env",
    "scan_secrets.py",
}

PATTERNS = [
    (r"\b(?!123456789012)\d{12}\b", "Unredacted 12-digit AWS Account ID"),
    (r"\b(EMy9MHuQZWowj9VGtHpKFR|UgC491Luruab4Tj5fXAcFR)\b", "Unredacted AVP Store ID"),
    (r"\b(NVL66r87jfHCEnJ11W1CU7|4ex1tmqMDDAssjf78bbtuE|HehFvFVPyKVHPgTVgRP2Ko)\b", "Unredacted AVP Policy ID"),
    (r"aws-cloudtrail-logs-\d{12}-[a-zA-Z0-9]+", "Unredacted CloudTrail Log Group ARN/Name"),
]

def scan_repo(root_dir: str) -> int:
    violations = []
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Exclude ignored directories
        dirnames[:] = [d for d in dirnames if d not in IGNORE_FILES and not d.startswith(".")]
        
        for fname in filenames:
            if fname in IGNORE_FILES or fname.endswith(".pyc"):
                continue
            fpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fpath, root_dir)
            
            # Skip infra template and sam configs which naturally contain deployment account/resources
            if relpath.startswith("infra") or relpath.startswith(".aws-sam"):
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        for pattern, desc in PATTERNS:
                            matches = re.findall(pattern, line)
                            if matches:
                                violations.append((relpath, line_no, desc, matches))
            except Exception as e:
                pass

    print("=== Pre-Push Redaction & Secret Scan ===")
    if violations:
        print(f"[FAIL] Found {len(violations)} redaction violation(s):")
        for relpath, line_no, desc, matches in violations:
            print(f"  * {relpath}:{line_no} - {desc}: {matches}")
        return 1
    else:
        print("[PASS] 0 unredacted secrets, store IDs, policy IDs, or account IDs found.")
        return 0

if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.exit(scan_repo(repo_root))
