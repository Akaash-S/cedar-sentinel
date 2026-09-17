"""
Cedar Sentinel CLI — Phase 1 Scaffolding
Reads Terraform plan JSON, extracts IAM policy definitions, and dispatches events.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import BotoCoreError, ClientError


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

        # Target IAM resources that define permissions
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
            # Extract inline policies or assume_role_policy if defined
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
            # Check for inline_policy array on role if present
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

    # Publish to EventBridge if requested or configured
    bus_name = args.event_bus or os.environ.get("EVENT_BUS_NAME")
    if args.publish or bus_name:
        effective_bus = bus_name or "default"
        source = args.source or "cedar.sentinel.test"
        detail_type = "TerraformPlanIamPolicyDetected"
        detail_payload = {
            "plan_file": os.path.basename(plan_path),
            "policy_count": len(policies),
            "policies": policies,
        }

        print(f"\nPublishing event to EventBridge bus '{effective_bus}' with source '{source}'...")
        try:
            resp = publish_event(
                event_bus_name=effective_bus,
                source=source,
                detail_type=detail_type,
                detail=detail_payload,
                region=args.region,
            )
            entries = resp.get("Entries", [])
            failed_count = resp.get("FailedEntryCount", 0)
            if failed_count == 0 and entries:
                print(f"Event published successfully! EventId: {entries[0].get('EventId')}")
            else:
                print(f"Warning: Failed to publish event: {resp}", file=sys.stderr)
                return 1
        except (BotoCoreError, ClientError) as err:
            print(f"Error publishing event to EventBridge: {err}", file=sys.stderr)
            return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Cedar Sentinel CLI — IAM Policy Extraction & Event Dispatcher"
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
        "analyze", help="Analyze Terraform plan JSON and extract IAM policies"
    )
    parser_analyze.add_argument(
        "--plan-file",
        required=True,
        help="Path to the JSON output of 'terraform show -json'",
    )
    parser_analyze.add_argument(
        "--publish",
        action="store_true",
        help="Publish extracted policy event to EventBridge",
    )
    parser_analyze.add_argument(
        "--event-bus",
        default=None,
        help="EventBridge bus name (overrides EVENT_BUS_NAME env var)",
    )
    parser_analyze.add_argument(
        "--source",
        default="cedar.sentinel.test",
        help="EventBridge event source (default: cedar.sentinel.test)",
    )
    parser_analyze.set_defaults(func=handle_analyze)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
