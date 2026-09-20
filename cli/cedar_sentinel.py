"""
Cedar Sentinel CLI — Phase 3: IAM Translation & Enforcement
Reads Terraform plan JSON, extracts IAM policy definitions, dispatches events,
polls DynamoDB for the Lambda pipeline result, and safely enforces tightened
IAM policies on target IAM roles with human-in-the-loop approval.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
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
POLL_TIMEOUT_SECONDS = 45


# ─────────────────────────────────────────────────────────────────
# Policy extraction helpers
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
# DynamoDB polling & status updates
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


def _update_result_status(
    table_name: str,
    request_id: str,
    status: str,
    error_message: Optional[str] = None,
    previous_policy: Optional[Any] = None,
    region: Optional[str] = None,
) -> None:
    """Updates the status and optional fields of a results item in DynamoDB."""
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    update_expr = "SET #s = :s"
    expr_names = {"#s": "status"}
    expr_vals: Dict[str, Any] = {":s": status}
    if error_message:
        update_expr += ", error_message = :em"
        expr_vals[":em"] = error_message
    if previous_policy is not None:
        update_expr += ", previous_policy = :pp"
        expr_vals[":pp"] = json.dumps(previous_policy) if isinstance(previous_policy, (dict, list)) else str(previous_policy)

    try:
        table.update_item(
            Key={"request_id": request_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
        )
    except Exception as exc:
        print(f"Warning: Failed to update DynamoDB status: {exc}", file=sys.stderr)


def _update_result_enforcement(
    table_name: str,
    request_id: str,
    status: str,
    previous_policy: Optional[Any] = None,
    other_policies: Optional[List[str]] = None,
    region: Optional[str] = None,
) -> None:
    """Updates enforcement fields in DynamoDB."""
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    update_expr = "SET #s = :s"
    expr_names = {"#s": "status"}
    expr_vals: Dict[str, Any] = {":s": status}
    if previous_policy is not None:
        update_expr += ", previous_policy = :pp"
        expr_vals[":pp"] = json.dumps(previous_policy) if isinstance(previous_policy, (dict, list)) else str(previous_policy)
    if other_policies:
        update_expr += ", other_policies = :op"
        expr_vals[":op"] = json.dumps(other_policies)

    try:
        table.update_item(
            Key={"request_id": request_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
        )
    except Exception as exc:
        print(f"Warning: Failed to update DynamoDB result: {exc}", file=sys.stderr)


def _update_result_audit_failure(
    table_name: str,
    request_id: str,
    audit_error: str,
    region: Optional[str] = None,
) -> None:
    """Records audit failure without changing final status from APPLIED."""
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)
    try:
        table.update_item(
            Key={"request_id": request_id},
            UpdateExpression="SET audit_failed = :af, audit_error = :ae",
            ExpressionAttributeValues={":af": True, ":ae": audit_error},
        )
    except Exception as exc:
        print(f"Warning: Failed to record audit failure in DynamoDB: {exc}", file=sys.stderr)


def _extract_cedar_actions(cedar_policy_text: str) -> List[str]:
    """Extracts action strings from Cedar policy text."""
    actions: List[str] = []
    pattern = re.compile(r'Action::\\?"([^\\"]+)\\?"')
    for match in pattern.finditer(cedar_policy_text):
        actions.append(match.group(1))

    if not actions:
        pattern2 = re.compile(r'\\?"([a-zA-Z0-9_*]+:[a-zA-Z0-9_*]+)\\?"')
        for match in pattern2.finditer(cedar_policy_text):
            actions.append(match.group(1))

    return list(set(actions))


def _policies_equal(doc1: Any, doc2: Any) -> bool:
    """Compares two IAM policy documents for logical equality."""
    if isinstance(doc1, str):
        try:
            doc1 = json.loads(doc1)
        except Exception:
            pass
    if isinstance(doc2, str):
        try:
            doc2 = json.loads(doc2)
        except Exception:
            pass
    return json.dumps(doc1, sort_keys=True) == json.dumps(doc2, sort_keys=True)


# ─────────────────────────────────────────────────────────────────
# Result rendering
# ─────────────────────────────────────────────────────────────────

def _render_before_after_diff(requested_policy: Any, cedar_policy: str, model_used: str = "") -> None:
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
    if model_used:
        print(f"  Reasoned by: {model_used}")
    print("=" * 60)
    print(cedar_policy)


def _render_complete_result(item: Dict[str, Any]) -> None:
    """Renders a COMPLETE pipeline result to stdout."""
    requested_policy_raw = item.get("requested_policy")
    cedar_policy = item.get("cedar_policy", "(no Cedar policy returned)")
    iam_policy = item.get("iam_policy")
    rationale = item.get("rationale", "")
    model_used = item.get("model_used", "")
    coverage = item.get("coverage_check", {})
    cedar_val = item.get("cedar_validation", {})
    analyzer_val = item.get("analyzer_validation", {})
    mappings_applied = item.get("action_mappings_applied", {})
    unmatched_actions = item.get("unmatched_actions", [])

    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = requested_policy_raw

    _render_before_after_diff(requested_policy, cedar_policy, model_used=model_used)

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

    print("\n" + "-" * 60)
    print("  IAM TRANSLATION & ACCESS ANALYZER VALIDATION")
    print("-" * 60)
    if iam_policy:
        print("[PASS] Translated tightened IAM policy generated successfully:")
        print(json.dumps(iam_policy, indent=2))
        if mappings_applied:
            print(f"\n  Action mappings applied: {mappings_applied}")
        if unmatched_actions:
            print(f"  [NOTE] Unmatched actions excluded without widening: {unmatched_actions}")
        if analyzer_val.get("passed"):
            print("\n  [PASS] IAM Access Analyzer validated syntax-valid and verified NO NEW ACCESS.")
        findings = analyzer_val.get("findings", [])
        if findings:
            print(f"  Non-blocking findings: {findings}")
    else:
        print("[NOTE] IAM translation not present in result.")

    print("\n" + "=" * 60)


def _render_cedar_invalid_result(item: Dict[str, Any]) -> None:
    """Renders a CEDAR_INVALID pipeline result to stdout."""
    requested_policy_raw = item.get("requested_policy")
    cedar_policy = item.get("cedar_policy", "(no Cedar policy returned)")
    rationale = item.get("rationale", "")
    model_used = item.get("model_used", "")
    cedar_val = item.get("cedar_validation", {})

    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = requested_policy_raw

    _render_before_after_diff(requested_policy, cedar_policy, model_used=model_used)

    print("\n" + "-" * 60)
    print("  RATIONALE")
    print("-" * 60)
    print(rationale)

    print("\n" + "=" * 60)
    print("  [FAIL] Cedar formal verification rejected the draft policy!")
    print("=" * 60)
    store_id = cedar_val.get("policy_store_id", "")
    if store_id:
        print(f"Policy Store: {store_id}")
    print("Validation Error(s):")
    messages = cedar_val.get("messages", [])
    if messages:
        for msg in messages:
            print(f"  * {msg}")
    else:
        print("  * Schema validation failed (no specific message returned).")
    print("\nOffending Cedar Policy Text:")
    print("-" * 40)
    print(cedar_policy)
    print("-" * 40)
    print("\nResult: Deployment blocked due to invalid Cedar policy syntax / schema mismatch.")


def _render_analyzer_invalid_result(item: Dict[str, Any]) -> None:
    """Renders an ANALYZER_INVALID pipeline result to stdout."""
    requested_policy_raw = item.get("requested_policy")
    cedar_policy = item.get("cedar_policy", "(no Cedar policy returned)")
    iam_policy = item.get("iam_policy", {})
    rationale = item.get("rationale", "")
    model_used = item.get("model_used", "")
    analyzer_val = item.get("analyzer_validation", {})

    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = requested_policy_raw

    _render_before_after_diff(requested_policy, cedar_policy, model_used=model_used)

    print("\n" + "-" * 60)
    print("  RATIONALE")
    print("-" * 60)
    print(rationale)

    print("\n" + "=" * 60)
    print("  [FAIL] IAM Access Analyzer rejected the translated policy!")
    print("=" * 60)
    reason = analyzer_val.get("reason", "UNKNOWN")
    print(f"Rejection Reason: {reason}")
    findings = analyzer_val.get("findings", [])
    if findings:
        print("Finding Details:")
        for f in findings:
            if isinstance(f, dict):
                code = f.get("code") or f.get("findingType") or "Finding"
                msg = f.get("message") or f.get("details") or str(f)
                print(f"  * [{code}] {msg}")
            else:
                print(f"  * {f}")
    else:
        print("  * Access Analyzer safety check failed (details unstated).")

    if iam_policy:
        print("\nTranslated IAM Policy:")
        print("-" * 40)
        print(json.dumps(iam_policy, indent=2) if isinstance(iam_policy, dict) else str(iam_policy))
        print("-" * 40)

    print("\nResult: Deployment blocked due to IAM Access Analyzer validation / escalation failure.")


def _render_blocked_result(item: Dict[str, Any]) -> int:
    """
    Renders the hard-block warning and interactive [1]/[2]/[3] menu.
    Returns the exit code from the selected option.
    """
    coverage = item.get("coverage_check", {})
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
        print("\n── Original Requested Policy ──────────────────────────")
        print(json.dumps(requested_policy, indent=2) if isinstance(requested_policy, dict) else str(requested_policy))
        print("───────────────────────────────────────────────────────")
        print("Reverted to original policy. No changes applied.")
        return 0

    elif choice == "2":
        # Section 4.6: Override is intentionally disabled in this build
        print(
            "\nOverride is intentionally disabled in this build: applying a policy that drops\n"
            "observed actions bypasses the lockout safeguard. Use [3] to re-evaluate or [1] to fall back."
        )
        return 1

    elif choice == "3":
        return _handle_reevaluate(item, blocked_actions)

    else:
        print(f"\nUnrecognized option '{choice}'. Exiting.", file=sys.stderr)
        return 1


def _handle_reevaluate(item: Dict[str, Any], blocked_actions: List[Dict]) -> int:
    """
    Option [3]: Re-invokes the pipeline with a re-evaluation hint injected
    into the event detail, so Bedrock receives the dropped actions explicitly.
    """
    new_request_id = str(uuid.uuid4())
    region = os.environ.get("AWS_REGION")
    bus_name = os.environ.get("EVENT_BUS_NAME", "cedar-sentinel-events")
    table_name = os.environ.get("RESULTS_TABLE_NAME", "cedar-sentinel-results")

    blocked_names = [ba.get("action", "") for ba in blocked_actions]
    reevaluate_hint = (
        f"IMPORTANT: The previous draft dropped these observed actions that MUST be "
        f"included: {', '.join(blocked_names)}. Preserve them in the new draft."
    )

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
    elif status == "CEDAR_INVALID":
        _render_cedar_invalid_result(result)
        return 1
    elif status == "ANALYZER_INVALID":
        _render_analyzer_invalid_result(result)
        return 1
    else:
        print(f"Re-evaluation ended with status: {status}", file=sys.stderr)
        err_msg = result.get("error_message", "")
        if err_msg:
            print(f"Error: {err_msg}", file=sys.stderr)
        return 1


# ─────────────────────────────────────────────────────────────────
# Persistent AVP Audit Store (Section 6)
# ─────────────────────────────────────────────────────────────────

def _record_persistent_audit_policy(
    cedar_policy_text: str,
    rationale: str,
    request_id: str,
    region: Optional[str] = None,
    ssm_param: str = "/cedar-sentinel/dev/avp-audit-store-id",
) -> Dict[str, Any]:
    """
    Writes the approved Cedar policy to the persistent AVP audit store.
    Registers STRICT schema if needed and creates a static policy record.
    """
    ssm_client = boto3.client("ssm", region_name=region)
    avp_client = boto3.client("verifiedpermissions", region_name=region)

    store_id = None
    try:
        resp = ssm_client.get_parameter(Name=ssm_param)
        candidate_id = resp["Parameter"]["Value"].strip()
        avp_client.get_policy_store(policyStoreId=candidate_id)
        store_id = candidate_id
    except Exception:
        pass

    if store_id is None:
        try:
            create_resp = avp_client.create_policy_store(
                validationSettings={"mode": "STRICT"},
                description="cedar-sentinel-audit-store (persistent audit record)",
            )
            store_id = create_resp["policyStoreId"]
            ssm_client.put_parameter(
                Name=ssm_param,
                Value=store_id,
                Type="String",
                Overwrite=True,
                Description="Cedar Sentinel persistent AVP audit store ID",
            )
        except Exception as exc:
            return {"success": False, "error": f"Failed to initialize persistent audit store: {exc}"}

    # Register schema on the audit store
    actions = _extract_cedar_actions(cedar_policy_text)
    if not actions:
        actions = ["none"]
    actions_schema = {}
    for act in sorted(set(actions)):
        actions_schema[act] = {
            "appliesTo": {
                "principalTypes": ["Role"],
                "resourceTypes": ["Resource"],
            }
        }
    schema = {
        "CedarSentinel": {
            "entityTypes": {
                "Role": {"shape": {"type": "Record", "attributes": {}}},
                "Resource": {"shape": {"type": "Record", "attributes": {}}},
            },
            "actions": actions_schema,
        }
    }

    try:
        avp_client.put_schema(
            policyStoreId=store_id,
            definition={"cedarJson": json.dumps(schema)},
        )
    except Exception as exc:
        return {"success": False, "error": f"PutSchema failed on audit store: {exc}"}

    # Write static policy into audit store (description capped to 140 chars per AVP constraints)
    desc = f"req={request_id[:8]} rationale={rationale}"[:140]
    try:
        cp_resp = avp_client.create_policy(
            policyStoreId=store_id,
            definition={
                "static": {
                    "description": desc,
                    "statement": cedar_policy_text,
                }
            },
        )
        return {
            "success": True,
            "policy_id": cp_resp["policyId"],
            "policy_store_id": store_id,
        }
    except Exception as exc:
        return {"success": False, "error": f"CreatePolicy failed on audit store: {exc}"}


# ─────────────────────────────────────────────────────────────────
# Enforcement & Apply Flow (Section 4 & 5)
# ─────────────────────────────────────────────────────────────────

def handle_apply_enforcement(
    args: argparse.Namespace,
    item: Dict[str, Any],
    region: Optional[str] = None,
) -> int:
    """
    Handles human-in-the-loop diff, confirmation, snapshotting,
    PutRolePolicy execution, read-back verification, and persistent audit recording.
    """
    table_name = os.environ.get("RESULTS_TABLE_NAME", "cedar-sentinel-results")
    request_id = item.get("request_id", "")
    role_arn = args.role_arn
    role_name = role_arn.split("/")[-1] if "/" in role_arn else role_arn.split(":")[-1]
    policy_name = args.policy_name
    iam_policy = item.get("iam_policy")
    if isinstance(iam_policy, str):
        try:
            iam_policy = json.loads(iam_policy)
        except Exception:
            pass

    if not iam_policy:
        print("Error: No translated IAM policy found in result item to apply.", file=sys.stderr)
        return 1

    iam_client = boto3.client("iam", region_name=region)

    # 1. Section 5.1: Confirm --policy-name exists on the target role
    try:
        list_resp = iam_client.list_role_policies(RoleName=role_name)
        existing_inline_policies = list_resp.get("PolicyNames", [])
    except ClientError as err:
        print(f"Error listing inline policies for role '{role_name}': {err}", file=sys.stderr)
        return 1

    if policy_name not in existing_inline_policies:
        print(
            f"\n[FAIL] Target inline policy name '{policy_name}' does not exist on role '{role_name}'.",
            file=sys.stderr,
        )
        print(f"Actual inline policies on role: {existing_inline_policies}", file=sys.stderr)
        print("Refusing to create a new parallel policy. Specify an existing inline policy name to overwrite.", file=sys.stderr)
        return 1

    # 2. Section 4.4: Print clear before/after diff + metadata
    requested_policy_raw = item.get("requested_policy")
    try:
        requested_policy = json.loads(requested_policy_raw) if isinstance(requested_policy_raw, str) else requested_policy_raw
    except Exception:
        requested_policy = requested_policy_raw

    print("\n" + "=" * 60)
    print("  PROPOSED IAM POLICY TO APPLY (Tightened & Verified)")
    print(f"  Target Role               : {role_arn}")
    print(f"  Target Inline Policy Name : {policy_name}")
    print("=" * 60)
    print("--- BEFORE: Requested Policy ---")
    print(json.dumps(requested_policy, indent=2) if isinstance(requested_policy, dict) else str(requested_policy))
    print("\n+++ AFTER: Translated Tightened Policy +++")
    print(json.dumps(iam_policy, indent=2))

    mappings = item.get("action_mappings_applied", {})
    if mappings:
        print(f"\n  Action mappings applied: {mappings}")
    unmatched = item.get("unmatched_actions", [])
    if unmatched:
        print(f"  [NOTE] Unmatched actions excluded without widening: {unmatched}")

    analyzer_val = item.get("analyzer_validation", {})
    findings = analyzer_val.get("findings", [])
    if findings:
        print(f"  Non-blocking Access Analyzer findings: {findings}")

    # 3. Prompt user explicitly: [y/N]
    prompt_msg = f"\nApply this policy to {role_arn}? [y/N]: "
    try:
        confirm = input(prompt_msg).strip()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm.lower() != "y":
        print("\nApply declined by user. No changes applied.")
        _update_result_status(table_name, request_id, "DECLINED", region=region)
        return 0

    # 4. Section 5.3: Snapshot existing policy before overwrite
    print(f"\nSnapshotting existing inline policy '{policy_name}' on role '{role_name}'...")
    previous_policy = None
    try:
        prev_resp = iam_client.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        previous_policy = prev_resp.get("PolicyDocument")
        print("[OK] Policy snapshotted successfully.")
    except ClientError as err:
        print(f"Warning: Could not snapshot existing policy: {err}", file=sys.stderr)

    # 5. Section 5.2: Apply via iam:PutRolePolicy with retry / backoff
    print(f"Applying tightened policy to role '{role_name}' (overwriting '{policy_name}')...")
    max_attempts = 3
    backoff = 1
    put_succeeded = False
    apply_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
                PolicyDocument=json.dumps(iam_policy),
            )
            put_succeeded = True
            break
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            msg = exc.response["Error"]["Message"]
            if code in ("Throttling", "ThrottlingException") and attempt < max_attempts:
                print(f"  [Attempt {attempt}] Throttled. Backing off {backoff}s...")
                time.sleep(backoff)
                backoff *= 2
                continue
            elif code in ("MalformedPolicyDocumentException", "LimitExceededException"):
                apply_error = f"{code}: {msg}"
                print(f"\n[FAIL] PutRolePolicy rejected: {apply_error}", file=sys.stderr)
                break
            else:
                apply_error = f"{code}: {msg}"
                print(f"\n[FAIL] PutRolePolicy failed: {apply_error}", file=sys.stderr)
                break

    if not put_succeeded:
        _update_result_status(
            table_name=table_name,
            request_id=request_id,
            status="APPLY_FAILED",
            error_message=apply_error,
            previous_policy=previous_policy,
            region=region,
        )
        return 1

    # 6. Section 5.4: Read-back verification with eventual-consistency retries
    print("Verifying applied policy via iam:GetRolePolicy read-back...")
    verified = False
    readback_doc = None
    for attempt in range(1, 4):
        time.sleep(1)
        try:
            rb_resp = iam_client.get_role_policy(RoleName=role_name, PolicyName=policy_name)
            readback_doc = rb_resp.get("PolicyDocument")
            if _policies_equal(readback_doc, iam_policy):
                verified = True
                break
        except ClientError as exc:
            pass

    final_status = "APPLIED" if verified else "APPLIED_UNVERIFIED"

    if verified:
        print(f"[SUCCESS] Policy successfully applied and verified on '{role_name}'.")
    else:
        print(f"[WARNING] PutRolePolicy succeeded, but read-back verification could not confirm consistency.")
        print(f"Status set to: APPLIED_UNVERIFIED. Please inspect role '{role_name}' manually.")

    # 7. Check for any other attached or inline policies on the role
    other_policies: List[str] = []
    try:
        post_inline = iam_client.list_role_policies(RoleName=role_name).get("PolicyNames", [])
        other_inline = [p for p in post_inline if p != policy_name]
        attached = iam_client.list_attached_role_policies(RoleName=role_name).get("AttachedPolicies", [])
        other_attached = [p.get("PolicyName", "") for p in attached]
        other_policies = other_inline + other_attached
    except ClientError as err:
        print(f"Warning: Could not check other attached policies: {err}", file=sys.stderr)

    if other_policies:
        print(f"\n[WARNING] Role has other policies that may still grant broad access: {', '.join(other_policies)}. Effective access is not fully tightened by this change.")

    # 8. Update DynamoDB result
    _update_result_enforcement(
        table_name=table_name,
        request_id=request_id,
        status=final_status,
        previous_policy=previous_policy,
        other_policies=other_policies,
        region=region,
    )

    # 9. Section 6: Audit trail write to persistent AVP audit store (only on APPLIED)
    if final_status == "APPLIED":
        cedar_policy = item.get("cedar_policy", "")
        rationale = item.get("rationale", "")
        print("\nRecording approved policy in persistent AVP audit store...")
        audit_res = _record_persistent_audit_policy(
            cedar_policy_text=cedar_policy,
            rationale=rationale,
            request_id=request_id,
            region=region,
        )
        if audit_res.get("success"):
            print(f"[AUDIT] Policy recorded in persistent AVP store {audit_res.get('policy_store_id')} (Policy ID: {audit_res.get('policy_id')})")
        else:
            print(f"[WARNING] Persistent audit store write failed: {audit_res.get('error')}", file=sys.stderr)
            _update_result_audit_failure(table_name, request_id, str(audit_res.get("error")), region=region)

    return 0


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

    # If --apply is specified without --publish, auto-enable publish since pipeline is required
    if args.apply:
        args.publish = True

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

    # ── Section 4.2 Guards on --apply (checked before dispatch / prompt) ──────
    role_arn_str = args.role_arn.strip()
    role_name = role_arn_str.split("/")[-1] if "/" in role_arn_str else role_arn_str.split(":")[-1]
    lambda_exec_role_arn = os.environ.get("LAMBDA_EXECUTION_ROLE_ARN", "").strip()

    if args.apply:
        if not args.policy_name:
            print("Error: --policy-name is required when --apply is specified.", file=sys.stderr)
            return 1

        # Guard 1: Refuse self-analysis / self-enforcement on Lambda execution role
        if lambda_exec_role_arn and role_arn_str == lambda_exec_role_arn:
            print(
                "Error: Target role matches Cedar Sentinel Lambda execution role. Self-modification via --apply is forbidden.",
                file=sys.stderr,
            )
            return 1

        # Guard 2: Refuse any role name not matching cedar-sentinel-*
        if not role_name.startswith("cedar-sentinel-"):
            print(
                f"Error: Target role '{role_name}' does not match allowed pattern 'cedar-sentinel-*'.\n"
                f"--apply is strictly restricted to roles named cedar-sentinel-*.",
                file=sys.stderr,
            )
            return 1

        # Guard 3: Confirm role exists and target inline policy exists before triggering pipeline
        try:
            iam_client = boto3.client("iam", region_name=args.region)
            list_resp = iam_client.list_role_policies(RoleName=role_name)
            existing_inline_policies = list_resp.get("PolicyNames", [])
            if args.policy_name not in existing_inline_policies:
                print(
                    f"\n[FAIL] Target inline policy name '{args.policy_name}' does not exist on role '{role_name}'.\n"
                    f"Actual inline policies on role: {existing_inline_policies}\n"
                    f"Refusing to create a new parallel policy. Specify an existing inline policy name to overwrite.",
                    file=sys.stderr,
                )
                return 1
        except ClientError as exc:
            err_code = exc.response["Error"]["Code"]
            if err_code == "NoSuchEntity":
                print(
                    f"\n[FAIL] Target role '{role_arn_str}' does not exist in target account/region.\n"
                    f"Refusing to proceed with apply. Verify role ARN.",
                    file=sys.stderr,
                )
                return 1
            print(f"Warning: Could not pre-verify IAM role/policy: {exc}", file=sys.stderr)
    else:
        # Self-analysis warning for read-only analyze
        if lambda_exec_role_arn and role_arn_str == lambda_exec_role_arn:
            if not getattr(args, "allow_self_analysis", False):
                print(
                    "[WARNING] Target role matches Cedar Sentinel's own execution role — results will reflect\n"
                    "the tool's own AWS calls, not a real workload.",
                    file=sys.stderr,
                )
                print(
                    "Pass --allow-self-analysis to proceed anyway (not recommended for real analysis).",
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

    # Guard 3: If --apply was requested, only COMPLETE status proceeds to enforcement
    if args.apply:
        if status != "COMPLETE":
            print(f"\n[REFUSED] Cannot apply: Pipeline result status is '{status}' (expected 'COMPLETE').", file=sys.stderr)
            if status == "BLOCKED":
                coverage = result.get("coverage_check", {})
                blocked_actions_raw = coverage.get("blocked_actions", "[]")
                try:
                    blocked_actions = json.loads(blocked_actions_raw) if isinstance(blocked_actions_raw, str) else blocked_actions_raw
                except Exception:
                    blocked_actions = []
                print("\n[WARNING] Potential Workload Lockout Detected: proposed policy drops observed actions:", file=sys.stderr)
                for ba in blocked_actions:
                    print(f"  - {ba.get('action')} (Observed {ba.get('observed_count')} times)", file=sys.stderr)
                print("Apply refused. Use analyze without --apply to inspect or re-evaluate.", file=sys.stderr)
                return 1
            elif status == "CEDAR_INVALID":
                _render_cedar_invalid_result(result)
                return 1
            elif status == "ANALYZER_INVALID":
                _render_analyzer_invalid_result(result)
                return 1
            elif status == "ERROR":
                print(f"Error: {result.get('error_message', 'No details available.')}", file=sys.stderr)
                return 1
            else:
                return 1

        # Proceed to human approval and apply
        return handle_apply_enforcement(args, result, region=args.region)

    # Read-only render flow (Phase 2 & Phase 3 print-only)
    if status == "COMPLETE":
        _render_complete_result(result)
        print(f"\nView this run: python cli/cedar_sentinel.py dashboard --run {request_id}")
        return 0
    elif status == "BLOCKED":
        return _render_blocked_result(result)
    elif status == "CEDAR_INVALID":
        _render_cedar_invalid_result(result)
        return 1
    elif status == "ANALYZER_INVALID":
        _render_analyzer_invalid_result(result)
        return 1
    elif status == "ERROR":
        print(f"\n[ERROR] Pipeline error for request_id={request_id}", file=sys.stderr)
        err_msg = result.get("error_message", "No details available.")
        print(f"  {err_msg}", file=sys.stderr)
        return 1
    else:
        print(f"\nUnknown status '{status}' for request_id={request_id}.", file=sys.stderr)
        return 1


def handle_dashboard(args: argparse.Namespace) -> int:
    """Handler for `dashboard` subcommand."""
    try:
        from cli.dashboard_server import DEFAULT_PORT, DEFAULT_TABLE_NAME, start_dashboard_server
    except ImportError:
        from dashboard_server import DEFAULT_PORT, DEFAULT_TABLE_NAME, start_dashboard_server

    table_name = getattr(args, "table", None) or os.environ.get("RESULTS_TABLE_NAME", DEFAULT_TABLE_NAME)
    start_dashboard_server(
        port=getattr(args, "port", DEFAULT_PORT),
        region=getattr(args, "region", None) or os.environ.get("AWS_REGION"),
        table_name=table_name,
        profile=getattr(args, "profile", None) or os.environ.get("AWS_PROFILE"),
        run_id=getattr(args, "run_id", None),
        no_open=getattr(args, "no_open", False),
        show_real_ids=getattr(args, "show_real_ids", False),
        offline_dir=getattr(args, "offline_dir", None),
    )
    return 0


# ─────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Cedar Sentinel CLI — IAM Policy Extraction, Bedrock Reasoning, Cedar Verification & IAM Enforcement"
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
        help="Analyze Terraform plan JSON, extract IAM policies, reason with Bedrock, verify with Cedar & Access Analyzer, and safely apply",
    )
    parser_analyze.add_argument(
        "--plan-file",
        required=True,
        help="Path to the JSON output of 'terraform show -json'",
    )
    parser_analyze.add_argument(
        "--role-arn",
        default=None,
        help="ARN of the IAM role to query CloudTrail history for (required when --publish or --apply is set)",
    )
    parser_analyze.add_argument(
        "--publish",
        action="store_true",
        help="Publish extracted policy event to EventBridge and poll for pipeline result",
    )
    parser_analyze.add_argument(
        "--apply",
        action="store_true",
        help="Apply the verified tightened IAM policy to the target role (requires confirmation prompt)",
    )
    parser_analyze.add_argument(
        "--policy-name",
        default=None,
        help="Name of the existing inline policy to overwrite on target role (required when --apply is specified)",
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
    parser_analyze.add_argument(
        "--allow-self-analysis",
        action="store_true",
        dest="allow_self_analysis",
        help="Allow analysis of Cedar Sentinel's own Lambda execution role (for read-only testing only; never permits --apply)",
    )
    parser_analyze.set_defaults(func=handle_analyze)

    # Subcommand: dashboard
    parser_dashboard = subparsers.add_parser(
        "dashboard",
        help="Start local read-only dashboard server bound to 127.0.0.1",
    )
    parser_dashboard.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind to on 127.0.0.1 (default: 8765)",
    )
    parser_dashboard.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS CLI profile name to use for credentials",
    )
    parser_dashboard.add_argument(
        "--table",
        default=None,
        help="DynamoDB results table name (defaults to RESULTS_TABLE_NAME env var or cedar-sentinel-results)",
    )
    parser_dashboard.add_argument(
        "--run",
        dest="run_id",
        default=None,
        help="Deep link to specific run request_id on open",
    )
    parser_dashboard.add_argument(
        "--no-open",
        action="store_true",
        help="Do not automatically open the browser on startup",
    )
    parser_dashboard.add_argument(
        "--show-real-ids",
        action="store_true",
        help="Do not sanitize/mask real AWS account IDs and ARNs (warning: not safe for screen recording)",
    )
    parser_dashboard.add_argument(
        "--offline-dir",
        default=None,
        help="Serve runs from local directory instead of connecting to AWS",
    )
    parser_dashboard.set_defaults(func=handle_dashboard)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
