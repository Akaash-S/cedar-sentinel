"""
Section 5 acceptance test — Option [2] stub.

Simulates selecting option [2] from the hard-block interactive menu and confirms:
  1. The printed message is exactly "Override not available until IAM enforcement exists in Phase 3."
  2. The function returns exit code 1 (non-zero).
"""

import importlib.util
import io
import os
import sys
from unittest.mock import patch

# Ensure Windows terminal doesn't crash on non-ASCII
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Load CLI module (can't import as package since directory is 'cli', not on sys.path by default)
_cli_path = os.path.join(os.path.dirname(__file__), "..", "cli", "cedar_sentinel.py")
_spec = importlib.util.spec_from_file_location("cedar_sentinel", _cli_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_render_blocked_result = _mod._render_blocked_result

BLOCKED_ITEM = {
    "status": "BLOCKED",
    "coverage_check": {
        "passed": False,
        "blocked_actions": '[{"action": "s3:GetObject", "observed_count": 5}]',
    },
    "cedar_policy": 'permit(principal, action == CedarSentinel::Action::"logs:PutLogEvents", resource);',
    "requested_policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}',
}

EXPECTED_MESSAGE = "Override not available until IAM enforcement exists in Phase 3."


def run_test() -> None:
    print("=" * 60)
    print("  Section 5 -- Option [2] stub acceptance test")
    print("=" * 60)
    print()

    # Capture stdout so we can assert the exact message
    captured = io.StringIO()

    with patch("builtins.input", return_value="2"):
        with patch("sys.stdout", new=captured):
            exit_code = _render_blocked_result(BLOCKED_ITEM)

    output = captured.getvalue()
    print(f"Captured output:\n{output}")
    print(f"Exit code returned: {exit_code}")

    ok = True

    if EXPECTED_MESSAGE in output:
        print(f'[PASS] Output contains exact Phase 3 stub message. OK')
    else:
        print(f'[FAIL] Expected message not found in output.')
        print(f'  Expected: {EXPECTED_MESSAGE!r}')
        ok = False

    if exit_code == 1:
        print("[PASS] Exit code is 1 (non-zero). OK")
    else:
        print(f"[FAIL] Expected exit code 1, got {exit_code}")
        ok = False

    print()
    print("=" * 60)
    print(f"  Overall: {'ALL TESTS PASSED' if ok else 'ONE OR MORE TESTS FAILED'}")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    run_test()
