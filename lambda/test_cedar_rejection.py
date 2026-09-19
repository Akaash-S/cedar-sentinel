"""
Section 5 acceptance test — Cedar rejection path.

Feeds a deliberately schema-violating Cedar policy into stage_cedar_validation
and asserts that the call reports it as invalid.

The policy references an action (FakeService::Action::"nonexistent:DoNothing") that is
absent from the schema registered alongside it, which should cause AVP's STRICT validator
to reject the policy.

Run locally with:
    AWS_REGION=ap-south-1 python -m lambda.test_cedar_rejection

Or invoke directly:
    cd cedar-sentinel
    python lambda/test_cedar_rejection.py

Requires valid AWS credentials with verifiedpermissions:* and ssm:* scoped to
/cedar-sentinel/* in the target region.
"""

import os
import sys

# Ensure Windows terminal doesn't crash on non-ASCII output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import importlib.util

# 'lambda' is a Python reserved keyword and cannot be used as a package name.
# Load handler.py directly via importlib.
_handler_path = os.path.join(os.path.dirname(__file__), "handler.py")
_spec = importlib.util.spec_from_file_location("handler", _handler_path)
_handler_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_handler_mod)
stage_cedar_validation = _handler_mod.stage_cedar_validation



INVALID_CEDAR_POLICY = (
    # References FakeService namespace and a nonexistent action — guaranteed not in schema
    'permit(principal, action == FakeService::Action::"nonexistent:DoNothing", resource);'
)

# A normal valid policy — used as the "passing" baseline alongside the invalid one
VALID_CEDAR_POLICY = (
    'permit(\n'
    '    principal,\n'
    '    action in [\n'
    '        CedarSentinel::Action::"logs:CreateLogGroup",\n'
    '        CedarSentinel::Action::"logs:PutLogEvents"\n'
    '    ],\n'
    '    resource\n'
    ');'
)

OBSERVED_ACTIONS = {
    "logs:CreateLogGroup": 5,
    "logs:PutLogEvents": 42,
}

SSM_PARAM = os.environ.get("AVP_POLICY_STORE_SSM_PARAM", "/cedar-sentinel/dev/avp-policy-store-id")
AVP_REGION = os.environ.get("AVP_REGION", os.environ.get("AWS_REGION", "ap-south-1"))


def run_tests() -> None:
    print("=" * 60)
    print("  Section 5 — Cedar rejection path acceptance test")
    print("=" * 60)
    print(f"  AVP region : {AVP_REGION}")
    print(f"  SSM param  : {SSM_PARAM}")
    print()

    # ── Test 1: Valid policy should PASS ────────────────────────────
    print("[TEST 1] Valid policy -> expect PASS")
    result1, _, _ = stage_cedar_validation(
        cedar_policy_text=VALID_CEDAR_POLICY,
        observed_actions=OBSERVED_ACTIONS,
        ssm_param=SSM_PARAM,
        avp_region=AVP_REGION,
    )
    if result1["passed"]:
        print("  [PASS] Valid policy accepted by AVP STRICT validator. ✓")
    else:
        print(f"  [FAIL] Valid policy rejected unexpectedly: {result1['messages']}")
    print()

    # ── Test 2: Invalid policy (wrong namespace) should FAIL ─────────
    print("[TEST 2] Schema-violating policy -> expect FAIL/rejection")
    result2, _, _ = stage_cedar_validation(
        cedar_policy_text=INVALID_CEDAR_POLICY,
        observed_actions=OBSERVED_ACTIONS,
        ssm_param=SSM_PARAM,
        avp_region=AVP_REGION,
    )
    if not result2["passed"]:
        print("  [PASS] Invalid policy correctly rejected by AVP. ✓")
        print(f"  Rejection messages: {result2['messages']}")
    else:
        print("  [FAIL] Invalid policy was NOT rejected — Cedar validation is not enforcing schema. ✗")
    print()

    # ── Summary ──────────────────────────────────────────────────────
    ok = result1["passed"] and not result2["passed"]
    print("=" * 60)
    print(f"  Overall: {'ALL TESTS PASSED ✓' if ok else 'ONE OR MORE TESTS FAILED ✗'}")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    run_tests()
