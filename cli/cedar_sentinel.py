"""
Cedar Sentinel CLI — Phase 2: Core Reasoning & Verification
Reads Terraform plan JSON, extracts IAM policy definitions, dispatches events,
and polls DynamoDB for the Lambda pipeline result.
"""

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Ensure Windows terminal stdout does not crash on unicode characters
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────
# DynamoDB polling config
# ─────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 30


# ─────────────────────────────────────────────────────────────────
# Policy extraction helpers (unchanged from Phase 1)
# ─────────────────────────────────────────────────────────────────

def get_caller_identity(region: Optional[str] = None) -> Dict[str, Any]:
    """Calls sts:GetCallerIdentity and returns identity details."""
    client = boto3.client("sts", region_name=region)
    identity = client.get_caller_identity()
    return {
        "Account": identity.get("Account"),
        "UserId": identity.get("UserId"),
        "Arn": identity.get("Arn"),
    }


def parse_policy_field(policy_value: Any) -> Any:
    """Safely decodes policy if it's a JSON-encoded string or already a dict."""
    if isinstance(policy_value, str):
        try:
            parsed = json.loads(policy_value)
            if isinstance(parsed, str):
                try:
                    return json.loads(parsed)
                except Exception:
                    return parsed
            return parsed
        except (json.JSONDecodeError, TypeError):
            return policy_value
    return policy_value


def extract_iam_policies_from_plan(plan_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Traverses resource_changes in a Terraform plan JSON and extracts
    IAM policy documents from relevant AWS IAM resources.
    """
    extracted_policies: List[Dict[str, Any]] = []
    resource_changes = plan_data.get("resource_changes", [])

    for res in resource_changes:
        res_type = res.get("type", "")
        res_name = res.get("name", "")
        res_address = res.get("address", "")
        change = res.get("change", {})
        actions = change.get("actions", [])
        after = change.get("after") or {}

        if res_type in (
            "aws_iam_policy",
            "aws_iam_role_policy",
            "aws_iam_user_policy",
            "aws_iam_group_policy",
        ):
            raw_policy = after.get("policy")
            if raw_policy:
                parsed_policy = parse_policy_field(raw_policy)
                extracted_policies.append(
                    {
                        "resource_address": res_address,
                        "resource_type": res_type,
                        "resource_name": res_name,
                        "actions": actions,
                        "role": after.get("role"),
                        "user": after.get("user"),
                        "group": after.get("group"),
                        "policy_name": after.get("name") or after.get("name_prefix"),
                        "policy_document": parsed_policy,
                    }
                )

        elif res_type == "aws_iam_role":
            assume_role_policy = after.get("assume_role_policy")
            if assume_role_policy:
                extracted_policies.append(
                    {
                        "resource_address": res_address,
                        "resource_type": res_type,
                        "resource_name": res_name,
                        "actions": actions,
                        "policy_name": "AssumeRolePolicyDocument",
                        "policy_document": parse_policy_field(assume_role_policy),
                    }
                )
            inline_policies = after.get("inline_policy")
            if isinstance(inline_policies, list):
                for inline in inline_policies:
                    if isinstance(inline, dict) and inline.get("policy"):
                        extracted_policies.append(
                            {
                                "resource_address": res_address,
                                "resource_type": res_type,
                                "resource_name": res_name,
                                "actions": actions,
                                "policy_name": inline.get("name"),
                                "policy_document": parse_policy_field(inline.get("policy")),
                            }
                        )

    return extracted_policies


def publish_event(
    event_bus_name: str,
    source: str,
    detail_type: str,
    detail: Dict[str, Any],
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Publishes an event to EventBridge."""
    events_client = boto3.client("events", region_name=region)
    entry = {
        "Source": source,
        "DetailType": detail_type,
        "Detail": json.dumps(detail),
        "EventBusName": event_bus_name,
    }
    response = events_client.put_events(Entries=[entry])
    return response


# ─────────────────────────────────────────────────────────────────
# DynamoDB polling
# ─────────────────────────────────────────────────────────────────

def poll_results_table(
    table_name: str,
    request_id: str,
    region: Optional[str] = None,
    timeout: int = POLL_TIMEOUT_SECONDS,
    interval: int = POLL_INTERVAL_SECONDS,
) -> Optional[Dict[str, Any]]:
    """
    Polls the DynamoDB results table every `interval` seconds until the item's
    status leaves 'PROCESSING', or until `timeout` seconds have elapsed.
    Returns the item dict, or None on timeout.
    """
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    deadline = time.time() + timeout

    print(f"\nPolling for result (request_id: {request_id})...")
    spinner = ["|", "/", "-", "\\"]
    spin_idx = 0

    while time.time() < deadline:
        try:
            response = table.get_item(Key={"request_id": request_id})
            item = response.get("Item")
            if item:
                status = item.get("status", "PROCESSING")
                if status != "PROCESSING":
                    print(f"\r[OK] Result ready (status: {status})          ")
                    return item
        except (BotoCoreError, ClientError) as err:
            print(f"\nWarning: DynamoDB poll error: {err}", file=sys.stderr)

        # Spinner tick
        print(f"\r  Waiting for Lambda result... {spinner[spin_idx % len(spinner)]}", end="", flush=True)
        spin_idx += 1
        time.sleep(interval)

    print(f"\r[FAIL] Timed out after {timeout}s waiting for result.          ")
    return None


# ─────────────────────────────────────────────────────────────────
# Result rendering
# ─────────────────────────────────────────────────────────────────

def _render_before_after_diff(requested_policy: Any, cedar_policy: str) -> None:
    """Prints a before/after diff of requested IAM policy vs. drafted Cedar policy."""
    print("\n" + "=" * 60)
    print("  BEFORE — Requested IAM Policy (from Terraform plan)")
    print("=" * 60)
    if isinstance(requested_policy, str):
        try:
            requested_policy = json.loads(requested_policy)
        except Exception:
            pass
    print(json.dumps(requested_policy, indent=2) if isinstance(requested_policy, dict) else str(requested_policy))

    print("\n" + "=" * 60)
    print("  AFTER  — Drafted Cedar Policy (Bedrock reasoning output)")
    print("=" * 60)
    print(cedar_policy)


def _render_complete_result(item: Dict[str, Any]) -> None:
    """Renders a COMPLETE pipeline result to stdout."""
    requested_policy_raw = item.get("requested_policy")
    cedar_policy = item.get("cedar_policy", "(no Cedar policy returned)")
    rationale = item.get("rationale", "")
    coverage = item.get("coverage_check", {})
    cedar_val = item.get("cedar_validation", {})

    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = requested_policy_raw

    _render_before_after_diff(requested_policy, cedar_policy)

    print("\n" + "-" * 60)
    print("  RATIONALE")
    print("-" * 60)
    print(rationale)

    print("\n" + "-" * 60)
    print("  COVERAGE CHECK")
    print("-" * 60)
    if coverage.get("passed"):
        print("[PASS] all observed actions are present in the draft policy.")
    else:
        print("[FAIL] see blocked actions above.")

    print("\n" + "-" * 60)
    print("  CEDAR FORMAL VERIFICATION")
    print("-" * 60)
    if cedar_val.get("passed"):
        print("[PASS] draft Cedar policy is schema-valid (STRICT mode).")
        store_id = cedar_val.get("policy_store_id", "")
        if store_id:
            print(f"  (Validated against disposable AVP policy store: {store_id})")
    else:
        print("[FAIL] Cedar schema validation errors:")
        for msg in cedar_val.get("messages", []):
            print(f"  * {msg}")

    print("\n" + "=" * 60)


def _render_blocked_result(item: Dict[str, Any]) -> int:
    """
    Renders the hard-block warning and interactive [1]/[2]/[3] menu.
    Returns the exit code from the selected option.
    """
    coverage = item.get("coverage_check", {})
    cedar_policy = item.get("cedar_policy", "")
    requested_policy_raw = item.get("requested_policy")

    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = requested_policy_raw

    blocked_actions_raw = coverage.get("blocked_actions", "[]")
    try:
        blocked_actions = json.loads(blocked_actions_raw) if isinstance(blocked_actions_raw, str) else blocked_actions_raw
    except Exception:
        blocked_actions = []

    # Exact warning format per Phase 2 spec Section 5
    print("\n[WARNING] SAFETY CHECK FAILED: Potential Workload Lockout Detected!")
    print("The proposed Cedar policy drops observed CloudTrail actions:")
    for ba in blocked_actions:
        action = ba.get("action", "unknown")
        count = ba.get("observed_count", 0)
        print(f"  - {action} (Observed {count} times in last 7 days)")
    print()
    print("Action Taken: Deployment blocked.")
    print("[1] Fall back to original policy")
    print("[2] Force-apply draft Cedar policy (Override)")
    print("[3] Re-evaluate with tighter prompt context")

    try:
        choice = input("\nSelect option [1/2/3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 1

    if choice == "1":
        # Print the original requested policy and exit 0
        print("\n── Original Requested Policy ──────────────────────────")
        print(json.dumps(requested_policy, indent=2) if isinstance(requested_policy, dict) else str(requested_policy))
        print("───────────────────────────────────────────────────────")
        print("Reverted to original policy. No changes applied.")
        return 0

    elif choice == "2":
        # Stub — Phase 3 will implement IAM enforcement
        print("\nOverride not available until IAM enforcement exists in Phase 3.")
        return 1

    elif choice == "3":
        # Re-publish with blocked actions explicitly in the prompt context
        return _handle_reevaluate(item, blocked_actions)

    else:
        print(f"\nUnrecognized option '{choice}'. Exiting.", file=sys.stderr)
        return 1


def _handle_reevaluate(item: Dict[str, Any], blocked_actions: List[Dict]) -> int:
    """
    Option [3]: Re-invokes the pipeline with a re-evaluation hint injected
    into the event detail, so Bedrock receives the dropped actions explicitly.
    Prints a new request_id and instructs the user to poll again (or auto-polls).
    """
    new_request_id = str(uuid.uuid4())
    region = os.environ.get("AWS_REGION")
    bus_name = os.environ.get("EVENT_BUS_NAME", "cedar-sentinel-events")
    table_name = os.environ.get("RESULTS_TABLE_NAME", "cedar-sentinel-results")

    # Reconstruct the re-evaluation detail — inject dropped actions hint
    blocked_names = [ba.get("action", "") for ba in blocked_actions]
    reevaluate_hint = (
        f"IMPORTANT: The previous draft dropped these observed actions that MUST be "
        f"included: {', '.join(blocked_names)}. Preserve them in the new draft."
    )

    # Pull original detail fields out of the DynamoDB item for re-publish
    requested_policy_raw = item.get("requested_policy", "{}")
    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = {}

    role_arn = item.get("role_arn", "")
    detail_payload = {
        "request_id": new_request_id,
        "role_arn": role_arn,
        "policies": [{"policy_document": requested_policy}],
        "reevaluate_hint": reevaluate_hint,
    }

    print(f"\nRe-evaluating with tighter prompt context...")
    print(f"New request_id: {new_request_id}")

    try:
        resp = publish_event(
            event_bus_name=bus_name,
            source="cedar.sentinel",
            detail_type="TerraformPlanIamPolicyDetected",
            detail=detail_payload,
            region=region,
        )
        failed = resp.get("FailedEntryCount", 0)
        if failed > 0:
            print("Warning: Failed to re-publish event.", file=sys.stderr)
            return 1
    except (BotoCoreError, ClientError) as err:
        print(f"Error re-publishing event: {err}", file=sys.stderr)
        return 1

    # Auto-poll the new result
    result = poll_results_table(
        table_name=table_name,
        request_id=new_request_id,
        region=region,
    )
    if result is None:
        print("Timed out waiting for re-evaluation result.", file=sys.stderr)
        return 1

    status = result.get("status", "UNKNOWN")
    if status == "COMPLETE":
        _render_complete_result(result)
        return 0
    elif status == "BLOCKED":
        return _render_blocked_result(result)
    else:
        print(f"Re-evaluation ended with status: {status}", file=sys.stderr)
        err_msg = result.get("error_message", "")
        if err_msg:
            print(f"Error: {err_msg}", file=sys.stderr)
        return 1


# ─────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────

def handle_check_aws(args: argparse.Namespace) -> int:
    """Handler for `check-aws` subcommand."""
    try:
        identity = get_caller_identity(region=args.region)
        print("=== AWS STS Caller Identity ===")
        print(f"Account ID : {identity['Account']}")
        print(f"User / ARN : {identity['Arn']}")
        print(f"User ID    : {identity['UserId']}")
        return 0
    except (BotoCoreError, ClientError) as err:
        print(f"Error checking AWS identity: {err}", file=sys.stderr)
        return 1


def handle_analyze(args: argparse.Namespace) -> int:
    """Handler for `analyze` subcommand."""
    plan_path = args.plan_file
    if not os.path.exists(plan_path):
        print(f"Error: Plan file not found: {plan_path}", file=sys.stderr)
        return 1

    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            plan_data = json.load(f)
    except Exception as err:
        print(f"Error reading plan JSON file '{plan_path}': {err}", file=sys.stderr)
        return 1

    policies = extract_iam_policies_from_plan(plan_data)

    print(f"=== Terraform Plan IAM Policy Extraction ===")
    print(f"Plan file: {plan_path}")
    print(f"Found {len(policies)} IAM policy definition(s):\n")

    for idx, p in enumerate(policies, 1):
        print(f"[{idx}] Resource: {p['resource_address']} ({p['resource_type']})")
        if p.get("role"):
            print(f"    Target Role: {p['role']}")
        if p.get("policy_name"):
            print(f"    Policy Name: {p['policy_name']}")
        print("    Policy Document:")
        print(json.dumps(p["policy_document"], indent=6))
        print("-" * 50)

    # Publish + pipeline path
    bus_name = args.event_bus or os.environ.get("EVENT_BUS_NAME")
    if not (args.publish or bus_name):
        return 0  # local extraction only — no pipeline

    if args.role_arn is None:
        print(
            "Error: --role-arn is required when publishing to the pipeline (--publish).",
            file=sys.stderr,
        )
        return 1

    effective_bus = bus_name or "cedar-sentinel-events"
    source = args.source or "cedar.sentinel"
    request_id = str(uuid.uuid4())

    detail_payload = {
        "request_id": request_id,
        "plan_file": os.path.basename(plan_path),
        "role_arn": args.role_arn,
        "policy_count": len(policies),
        "policies": policies,
    }

    print(f"\nPublishing analysis event to EventBridge bus '{effective_bus}'...")
    print(f"Request ID: {request_id}")

    try:
        resp = publish_event(
            event_bus_name=effective_bus,
            source=source,
            detail_type="TerraformPlanIamPolicyDetected",
            detail=detail_payload,
            region=args.region,
        )
        failed_count = resp.get("FailedEntryCount", 0)
        entries = resp.get("Entries", [])
        if failed_count == 0 and entries:
            print(f"Event published. EventId: {entries[0].get('EventId')}")
        else:
            print(f"Warning: Failed to publish event: {resp}", file=sys.stderr)
            return 1
    except (BotoCoreError, ClientError) as err:
        print(f"Error publishing event to EventBridge: {err}", file=sys.stderr)
        return 1

    # Poll the results table
    table_name = os.environ.get("RESULTS_TABLE_NAME", "cedar-sentinel-results")
    result = poll_results_table(
        table_name=table_name,
        request_id=request_id,
        region=args.region,
        timeout=POLL_TIMEOUT_SECONDS,
        interval=POLL_INTERVAL_SECONDS,
    )

    if result is None:
        print(
            f"\nTimeout: no result received after {POLL_TIMEOUT_SECONDS}s. "
            f"Check CloudWatch logs for request_id={request_id}.",
            file=sys.stderr,
        )
        return 1

    status = result.get("status", "UNKNOWN")

    if status == "COMPLETE":
        _render_complete_result(result)
        return 0
    elif status == "BLOCKED":
        return _render_blocked_result(result)
    elif status == "ERROR":
        print(f"\n[ERROR] Pipeline error for request_id={request_id}", file=sys.stderr)
        err_msg = result.get("error_message", "No details available.")
        print(f"  {err_msg}", file=sys.stderr)
        return 1
    else:
        print(f"\nUnknown status '{status}' for request_id={request_id}.", file=sys.stderr)
        return 1


# ─────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Cedar Sentinel CLI — IAM Policy Extraction, Bedrock Reasoning & Cedar Verification"
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION"),
        help="AWS region (defaults to AWS_REGION env or AWS config)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: check-aws
    parser_check = subparsers.add_parser("check-aws", help="Check AWS STS Caller Identity")
    parser_check.set_defaults(func=handle_check_aws)

    # Subcommand: analyze
    parser_analyze = subparsers.add_parser(
        "analyze",
        help="Analyze Terraform plan JSON, extract IAM policies, reason with Bedrock, verify with Cedar",
    )
    parser_analyze.add_argument(
        "--plan-file",
        required=True,
        help="Path to the JSON output of 'terraform show -json'",
    )
    parser_analyze.add_argument(
        "--role-arn",
        default=None,
        help="ARN of the IAM role to query CloudTrail history for (required when --publish is set)",
    )
    parser_analyze.add_argument(
        "--publish",
        action="store_true",
        help="Publish extracted policy event to EventBridge and poll for pipeline result",
    )
    parser_analyze.add_argument(
        "--event-bus",
        default=None,
        help="EventBridge bus name (overrides EVENT_BUS_NAME env var)",
    )
    parser_analyze.add_argument(
        "--source",
        default="cedar.sentinel",
        help="EventBridge event source (default: cedar.sentinel)",
    )
    parser_analyze.set_defaults(func=handle_analyze)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
