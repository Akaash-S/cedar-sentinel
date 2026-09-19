#!/usr/bin/env python3
"""
Integration / unit test suite for Stage 6: IAM Access Analyzer Independent Safety Net.
Verifies all Section 3 acceptance criteria against live AWS Access Analyzer in ap-south-1.
"""

import json
import os
import sys
import unittest

from handler import stage_access_analyzer

REGION = os.environ.get("AWS_REGION", "ap-south-1")


class TestAccessAnalyzerSafetyNet(unittest.TestCase):

    def test_a_invalid_action_name_triggers_validation_error(self):
        """Case (a): Invalid action name triggers ERROR finding and VALIDATION_ERROR rejection."""
        invalid_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:InvalidNonExistentActionXYZ"],
                    "Resource": "*"
                }
            ]
        }
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": "*"
                }
            ]
        }

        result, _, _ = stage_access_analyzer(invalid_policy, requested_policy, region=REGION)
        print("\n--- Case (a) Invalid Action Name Test ---")
        print(f"Passed: {result['passed']}, Reason: {result.get('reason')}")
        print("Messages:", result.get("messages"))
        print("Findings count:", len(result.get("findings", [])))
        for f in result.get("findings", []):
            print(f"  * FindingType: {f.get('findingType')}, IssueCode: {f.get('issueCode')}, Details: {f.get('findingDetails')}")

        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "VALIDATION_ERROR")
        error_findings = [f for f in result.get("findings", []) if f.get("findingType") == "ERROR"]
        self.assertTrue(len(error_findings) > 0)

    def test_b_over_permissive_policy_non_blocking_findings(self):
        """Case (b): Over-permissive policy (Resource: '*' with wildcard action) returns non-blocking findings."""
        over_permissive_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": "*"
                }
            ]
        }
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["*"],
                    "Resource": "*"
                }
            ]
        }

        result, _, _ = stage_access_analyzer(over_permissive_policy, requested_policy, region=REGION)
        print("\n--- Case (b) Over-Permissive Policy Test ---")
        print(f"Passed: {result['passed']}, Reason: {result.get('reason')}")
        print("Messages:", result.get("messages"))
        print("Findings count:", len(result.get("findings", [])))
        for f in result.get("findings", []):
            print(f"  * FindingType: {f.get('findingType')}, IssueCode: {f.get('issueCode')}, Details: {f.get('findingDetails')}")

        # Unless there is a syntax ERROR, this should pass validation (findings are warnings/suggestions)
        error_findings = [f for f in result.get("findings", []) if f.get("findingType") == "ERROR"]
        self.assertEqual(len(error_findings), 0)
        self.assertTrue(result["passed"])

    def test_c_clean_tightly_scoped_policy_passes(self):
        """Case (c): Clean, tightly scoped policy passes without blocking findings."""
        clean_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "TightlyScopedS3",
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:PutObject"
                    ],
                    "Resource": "arn:aws:s3:::my-test-bucket/*"
                }
            ]
        }
        requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": "arn:aws:s3:::my-test-bucket/*"
                }
            ]
        }

        result, _, _ = stage_access_analyzer(clean_policy, requested_policy, region=REGION)
        print("\n--- Case (c) Clean Tightly-Scoped Policy Test ---")
        print(f"Passed: {result['passed']}, Reason: {result.get('reason')}")
        print("Messages:", result.get("messages"))
        print("CheckNoNewAccess result:", result.get("check_no_new_access", {}).get("result"))

        self.assertTrue(result["passed"])
        self.assertIsNone(result["reason"])
        self.assertEqual(result.get("check_no_new_access", {}).get("result"), "PASS")

    def test_d_check_no_new_access_catches_escalation(self):
        """Case (d): CheckNoNewAccess catches new permissions not in requested policy -> NEW_ACCESS."""
        # Translated policy grants DynamoDB PutItem
        escalating_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:PutItem"],
                    "Resource": "*"
                }
            ]
        }
        # But requested policy only allowed S3!
        narrow_requested_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": "arn:aws:s3:::specific-bucket/*"
                }
            ]
        }

        result, _, _ = stage_access_analyzer(escalating_policy, narrow_requested_policy, region=REGION)
        print("\n--- Case (d) Privilege Escalation Check Test ---")
        print(f"Passed: {result['passed']}, Reason: {result.get('reason')}")
        print("Messages:", result.get("messages"))
        print("CheckNoNewAccess detail:", result.get("check_no_new_access"))

        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "NEW_ACCESS")
        self.assertEqual(result.get("check_no_new_access", {}).get("result"), "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
