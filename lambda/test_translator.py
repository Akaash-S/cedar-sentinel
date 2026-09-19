#!/usr/bin/env python3
"""
Unit tests for Stage 5: Cedar to IAM Policy Translation & Action Normalization.
Verifies all Section 2.5 requirements in instructions/phase-03-enforcement.md.
"""

import json
import sys
import unittest

from handler import stage_iam_translation


class TestCedarToIamTranslator(unittest.TestCase):

    def test_1_single_action_policy(self):
        """Test 1: Single-action policy translates to standard IAM JSON."""
        cedar_policy = """
        permit(
            principal,
            action in [CedarSentinel::Action::"s3:GetObject"],
            resource
        );
        """
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3Access",
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": "arn:aws:s3:::my-bucket/*"
                }
            ]
        }

        result, s_start, s_end = stage_iam_translation(cedar_policy, requested_policy)
        iam_doc = result["iam_policy"]

        self.assertEqual(iam_doc["Version"], "2012-10-17")
        self.assertEqual(len(iam_doc["Statement"]), 1)
        stmt = iam_doc["Statement"][0]
        self.assertEqual(stmt["Effect"], "Allow")
        self.assertEqual(stmt["Action"], ["s3:GetObject"])
        self.assertEqual(stmt["Resource"], "arn:aws:s3:::my-bucket/*")
        self.assertEqual(result["unmatched_actions"], [])
        self.assertEqual(result["action_mappings_applied"], [])
        print("\n[Test 1 PASS] Single-action translation verified.")
        print(json.dumps(iam_doc, indent=2))

    def test_2_multi_service_multi_action_policy(self):
        """Test 2: Multi-service multi-action policy grouped by resource."""
        cedar_policy = """
        permit(
            principal,
            action in [
                CedarSentinel::Action::"s3:GetObject",
                CedarSentinel::Action::"s3:PutObject",
                CedarSentinel::Action::"logs:CreateLogGroup",
                CedarSentinel::Action::"logs:PutLogEvents"
            ],
            resource
        );
        """
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3BucketAccess",
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": "arn:aws:s3:::demo-bucket/*"
                },
                {
                    "Sid": "LogsAccess",
                    "Effect": "Allow",
                    "Action": ["logs:*"],
                    "Resource": "arn:aws:logs:*:*:*"
                }
            ]
        }

        result, _, _ = stage_iam_translation(cedar_policy, requested_policy)
        iam_doc = result["iam_policy"]

        self.assertEqual(len(iam_doc["Statement"]), 2)
        # Find S3 and Logs statements
        s3_stmt = next(s for s in iam_doc["Statement"] if s["Resource"] == "arn:aws:s3:::demo-bucket/*")
        logs_stmt = next(s for s in iam_doc["Statement"] if s["Resource"] == "arn:aws:logs:*:*:*")

        self.assertEqual(s3_stmt["Action"], ["s3:GetObject", "s3:PutObject"])
        self.assertEqual(logs_stmt["Action"], ["logs:CreateLogGroup", "logs:PutLogEvents"])
        self.assertEqual(result["unmatched_actions"], [])
        print("\n[Test 2 PASS] Multi-service multi-action grouped translation verified.")
        print(json.dumps(iam_doc, indent=2))

    def test_3_cloudtrail_action_normalization(self):
        """Test 3: Policy containing s3:ListBuckets becomes s3:ListAllMyBuckets and records mapping."""
        cedar_policy = """
        permit(
            principal,
            action in [
                CedarSentinel::Action::"s3:ListBuckets",
                CedarSentinel::Action::"s3:CreateBucket"
            ],
            resource
        );
        """
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "BroadS3",
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": "*"
                }
            ]
        }

        result, _, _ = stage_iam_translation(cedar_policy, requested_policy)
        iam_doc = result["iam_policy"]

        stmt = iam_doc["Statement"][0]
        # s3:ListBuckets must be translated to s3:ListAllMyBuckets
        self.assertIn("s3:ListAllMyBuckets", stmt["Action"])
        self.assertNotIn("s3:ListBuckets", stmt["Action"])
        self.assertIn("s3:CreateBucket", stmt["Action"])

        # Check action_mappings_applied
        mappings = result["action_mappings_applied"]
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["original"], "s3:ListBuckets")
        self.assertEqual(mappings[0]["mapped"], "s3:ListAllMyBuckets")
        print("\n[Test 3 PASS] Action mapping s3:ListBuckets -> s3:ListAllMyBuckets verified.")
        print("Applied mappings:", mappings)
        print(json.dumps(iam_doc, indent=2))

    def test_4_unmatched_action_excluded_not_widened(self):
        """Test 4: Action matching no requested statement is excluded and recorded, not widened to '*'."""
        cedar_policy = """
        permit(
            principal,
            action in [
                CedarSentinel::Action::"s3:GetObject",
                CedarSentinel::Action::"dynamodb:PutItem"
            ],
            resource
        );
        """
        # Requested policy only grants S3, NOT DynamoDB
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3Only",
                    "Effect": "Allow",
                    "Action": ["s3:Get*", "s3:List*"],
                    "Resource": "arn:aws:s3:::specific-bucket/*"
                }
            ]
        }

        result, _, _ = stage_iam_translation(cedar_policy, requested_policy)
        iam_doc = result["iam_policy"]

        # Only S3 action is included
        self.assertEqual(len(iam_doc["Statement"]), 1)
        stmt = iam_doc["Statement"][0]
        self.assertEqual(stmt["Action"], ["s3:GetObject"])
        self.assertEqual(stmt["Resource"], "arn:aws:s3:::specific-bucket/*")

        # DynamoDB action must be in unmatched_actions and NOT present in the output
        self.assertIn("dynamodb:PutItem", result["unmatched_actions"])
        print("\n[Test 4 PASS] Unmatched action excluded without widening to '*' verified.")
        print("Unmatched actions:", result["unmatched_actions"])
        print(json.dumps(iam_doc, indent=2))

    def test_5_forbid_statement_refused(self):
        """Test 5: Policy with a forbid block causes the translator to refuse and raise ValueError."""
        cedar_policy = """
        forbid(
            principal,
            action in [CedarSentinel::Action::"none"],
            resource
        );
        """
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "*",
                    "Resource": "*"
                }
            ]
        }

        with self.assertRaises(ValueError) as ctx:
            stage_iam_translation(cedar_policy, requested_policy)

        self.assertIn("Translator refused", str(ctx.exception))
        self.assertIn("forbid", str(ctx.exception))
        print("\n[Test 5 PASS] Forbid statement refusal verified:")
        print(str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
