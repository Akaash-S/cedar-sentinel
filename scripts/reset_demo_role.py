#!/usr/bin/env python3
"""
Reset script for Cedar Sentinel demo role.
Restores cedar-sentinel-demo-role's inline policy to the broad "before" state (demo-broad-s3).
Hard-coded to refuse any other role.
"""

import argparse
import json
import os
import sys
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Ensure Windows terminal stdout does not crash on unicode characters
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ALLOWED_ROLE_NAME = "cedar-sentinel-demo-role"
DEFAULT_POLICY_NAME = "demo-broad-s3"

BROAD_DEMO_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DemoS3Access",
            "Effect": "Allow",
            "Action": "s3:*",
            "Resource": "*"
        }
    ]
}


def reset_demo_role(role_name: str, policy_name: str, region: str) -> int:
    if role_name != ALLOWED_ROLE_NAME:
        print(f"Error: reset_demo_role is hard-coded to only modify '{ALLOWED_ROLE_NAME}'.", file=sys.stderr)
        print(f"Attempted role: '{role_name}' — REFUSED.", file=sys.stderr)
        return 1

    iam = boto3.client("iam", region_name=region)

    print(f"=== Cedar Sentinel Demo Role Reset ===")
    print(f"Target Role: {role_name}")
    print(f"Policy Name: {policy_name}")
    print(f"Region     : {region}")

    # 1. Fetch current policy before reset
    print("\n--- Policy BEFORE Reset ---")
    try:
        before_resp = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        before_doc = before_resp.get("PolicyDocument")
        print(json.dumps(before_doc, indent=2))
    except ClientError as err:
        if err.response["Error"]["Code"] == "NoSuchEntity":
            print(f"(Policy '{policy_name}' does not currently exist on role '{role_name}')")
        else:
            print(f"Error fetching existing policy: {err}", file=sys.stderr)
            return 1

    # 2. Put broad policy
    print("\nApplying broad baseline policy...")
    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(BROAD_DEMO_POLICY),
        )
        print("[OK] PutRolePolicy succeeded.")
    except ClientError as err:
        print(f"Error updating role policy: {err}", file=sys.stderr)
        return 1

    # 3. Read back policy after reset
    print("\n--- Policy AFTER Reset ---")
    try:
        after_resp = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        after_doc = after_resp.get("PolicyDocument")
        print(json.dumps(after_doc, indent=2))
    except ClientError as err:
        print(f"Error verifying policy after reset: {err}", file=sys.stderr)
        return 1

    print("\n[SUCCESS] Demo role reset to broad 'before' state completed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset cedar-sentinel-demo-role to broad baseline policy.")
    parser.add_argument(
        "--role-name",
        default=ALLOWED_ROLE_NAME,
        help=f"Target role name (MUST be '{ALLOWED_ROLE_NAME}')",
    )
    parser.add_argument(
        "--policy-name",
        default=DEFAULT_POLICY_NAME,
        help=f"Inline policy name to reset (default: '{DEFAULT_POLICY_NAME}')",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "ap-south-1"),
        help="AWS Region (default: ap-south-1)",
    )
    args = parser.parse_args()
    sys.exit(reset_demo_role(args.role_name, args.policy_name, args.region))


if __name__ == "__main__":
    main()
