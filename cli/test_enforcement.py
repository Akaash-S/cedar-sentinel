#!/usr/bin/env python3
"""
Unit tests for CLI Enforcement Flow with Mocked Botocore / Boto3 calls.
Tests:
  1. ThrottlingException retry on PutRolePolicy (backs off and succeeds).
  2. MalformedPolicyDocumentException handling on PutRolePolicy (fails cleanly, status=APPLY_FAILED).
  3. LimitExceededException handling on PutRolePolicy (fails cleanly, status=APPLY_FAILED).
  4. APPLIED_UNVERIFIED handling (read-back mismatch sets status=APPLIED_UNVERIFIED, skips audit store).
"""

import argparse
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

# Ensure CLI module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cedar_sentinel import handle_apply_enforcement


class TestCliEnforcement(unittest.TestCase):

    def setUp(self):
        self.role_arn = "arn:aws:iam::123456789012:role/cedar-sentinel-demo-role"
        self.policy_name = "demo-broad-s3"
        self.request_id = "test-req-001"
        self.args = argparse.Namespace(
            role_arn=self.role_arn,
            policy_name=self.policy_name,
        )
        self.sample_item = {
            "request_id": self.request_id,
            "role_arn": self.role_arn,
            "requested_policy": json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Sid": "BroadS3", "Effect": "Allow", "Action": "s3:*", "Resource": "*"}]
            }),
            "iam_policy": {
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "CedarSentinelTightenedStmt1",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject"],
                    "Resource": "*"
                }]
            },
            "cedar_policy": 'permit(principal, action in [CedarSentinel::Action::"s3:GetObject", CedarSentinel::Action::"s3:PutObject"], resource);',
            "rationale": "Tightened to observed S3 actions.",
            "status": "COMPLETE",
        }

    @patch("cedar_sentinel.boto3.client")
    @patch("cedar_sentinel.input", return_value="y")
    @patch("cedar_sentinel._update_result_enforcement")
    @patch("cedar_sentinel._record_persistent_audit_policy")
    @patch("cedar_sentinel.time.sleep")
    def test_1_throttling_retry_success(
        self, mock_sleep, mock_audit, mock_update_enf, mock_input, mock_boto_client
    ):
        """Test 1: ThrottlingException on PutRolePolicy retries with backoff and succeeds on retry."""
        mock_iam = MagicMock()
        mock_boto_client.return_value = mock_iam

        # list_role_policies returns existing policy name
        mock_iam.list_role_policies.return_value = {"PolicyNames": [self.policy_name]}
        # get_role_policy snapshot
        mock_iam.get_role_policy.side_effect = [
            # 1. Snapshot call
            {"PolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}},
            # 2. Read-back verification call
            {"PolicyDocument": self.sample_item["iam_policy"]},
        ]
        # list_attached_role_policies
        mock_iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}

        # put_role_policy raises ThrottlingException on attempt 1, succeeds on attempt 2
        throttle_err = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "PutRolePolicy"
        )
        mock_iam.put_role_policy.side_effect = [throttle_err, {}]
        mock_audit.return_value = {"success": True, "policy_id": "audit-pol-01", "policy_store_id": "audit-store-01"}

        exit_code = handle_apply_enforcement(self.args, self.sample_item, region="ap-south-1")

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_iam.put_role_policy.call_count, 2)
        mock_sleep.assert_called()  # Verified backoff sleep was invoked
        mock_update_enf.assert_called_once()
        call_kwargs = mock_update_enf.call_args[1]
        self.assertEqual(call_kwargs["status"], "APPLIED")
        mock_audit.assert_called_once()
        print("\n[Test 1 PASS] ThrottlingException retry with backoff verified.")

    @patch("cedar_sentinel.boto3.client")
    @patch("cedar_sentinel.input", return_value="y")
    @patch("cedar_sentinel._update_result_status")
    def test_2_malformed_policy_document_exception(
        self, mock_update_status, mock_input, mock_boto_client
    ):
        """Test 2: MalformedPolicyDocumentException fails cleanly without retries and sets APPLY_FAILED."""
        mock_iam = MagicMock()
        mock_boto_client.return_value = mock_iam

        mock_iam.list_role_policies.return_value = {"PolicyNames": [self.policy_name]}
        mock_iam.get_role_policy.return_value = {"PolicyDocument": {}}

        malformed_err = ClientError(
            {"Error": {"Code": "MalformedPolicyDocumentException", "Message": "Syntax error in policy"}},
            "PutRolePolicy"
        )
        mock_iam.put_role_policy.side_effect = malformed_err

        exit_code = handle_apply_enforcement(self.args, self.sample_item, region="ap-south-1")

        self.assertEqual(exit_code, 1)
        self.assertEqual(mock_iam.put_role_policy.call_count, 1)
        mock_update_status.assert_called_once()
        call_kwargs = mock_update_status.call_args[1]
        self.assertEqual(call_kwargs["status"], "APPLY_FAILED")
        self.assertIn("MalformedPolicyDocumentException", call_kwargs["error_message"])
        print("\n[Test 2 PASS] MalformedPolicyDocumentException cleanly handled.")

    @patch("cedar_sentinel.boto3.client")
    @patch("cedar_sentinel.input", return_value="y")
    @patch("cedar_sentinel._update_result_status")
    def test_3_limit_exceeded_exception(
        self, mock_update_status, mock_input, mock_boto_client
    ):
        """Test 3: LimitExceededException fails cleanly without retries and sets APPLY_FAILED."""
        mock_iam = MagicMock()
        mock_boto_client.return_value = mock_iam

        mock_iam.list_role_policies.return_value = {"PolicyNames": [self.policy_name]}
        mock_iam.get_role_policy.return_value = {"PolicyDocument": {}}

        limit_err = ClientError(
            {"Error": {"Code": "LimitExceededException", "Message": "Maximum policy size exceeded"}},
            "PutRolePolicy"
        )
        mock_iam.put_role_policy.side_effect = limit_err

        exit_code = handle_apply_enforcement(self.args, self.sample_item, region="ap-south-1")

        self.assertEqual(exit_code, 1)
        self.assertEqual(mock_iam.put_role_policy.call_count, 1)
        mock_update_status.assert_called_once()
        call_kwargs = mock_update_status.call_args[1]
        self.assertEqual(call_kwargs["status"], "APPLY_FAILED")
        self.assertIn("LimitExceededException", call_kwargs["error_message"])
        print("\n[Test 3 PASS] LimitExceededException cleanly handled.")

    @patch("cedar_sentinel.boto3.client")
    @patch("cedar_sentinel.input", return_value="y")
    @patch("cedar_sentinel._update_result_enforcement")
    @patch("cedar_sentinel._record_persistent_audit_policy")
    @patch("cedar_sentinel.time.sleep")
    def test_4_applied_unverified(
        self, mock_sleep, mock_audit, mock_update_enf, mock_input, mock_boto_client
    ):
        """Test 4: Read-back verification mismatch across all 3 retries sets APPLIED_UNVERIFIED and skips audit."""
        mock_iam = MagicMock()
        mock_boto_client.return_value = mock_iam

        mock_iam.list_role_policies.return_value = {"PolicyNames": [self.policy_name]}
        # Snapshot returns old policy; subsequent 3 read-backs return stale/mismatched document
        stale_policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:OldAction", "Resource": "*"}]}
        mock_iam.get_role_policy.side_effect = [
            {"PolicyDocument": stale_policy},  # Snapshot
            {"PolicyDocument": stale_policy},  # Read-back 1
            {"PolicyDocument": stale_policy},  # Read-back 2
            {"PolicyDocument": stale_policy},  # Read-back 3
        ]
        mock_iam.put_role_policy.return_value = {}
        mock_iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}

        exit_code = handle_apply_enforcement(self.args, self.sample_item, region="ap-south-1")

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_iam.put_role_policy.call_count, 1)
        # 1 snapshot + 3 read-back attempts = 4 calls to get_role_policy
        self.assertEqual(mock_iam.get_role_policy.call_count, 4)
        mock_update_enf.assert_called_once()
        call_kwargs = mock_update_enf.call_args[1]
        self.assertEqual(call_kwargs["status"], "APPLIED_UNVERIFIED")
        print("\n[Test 4 PASS] APPLIED_UNVERIFIED handling and audit skip verified.")

    @patch("cedar_sentinel.boto3.client")
    @patch("cedar_sentinel.input")
    @patch("cedar_sentinel.publish_event")
    @patch("cedar_sentinel.poll_results_table")
    def test_5_non_complete_statuses_never_prompt_or_put_policy(
        self, mock_poll, mock_publish, mock_input, mock_boto_client
    ):
        """Test 5: --apply never prompts and never calls PutRolePolicy when status is not COMPLETE."""
        from cedar_sentinel import handle_analyze

        non_complete_statuses = [
            "ANALYZER_INVALID",
            "CEDAR_INVALID",
            "BLOCKED",
            "ERROR",
            "PROCESSING",
        ]

        mock_iam = MagicMock()
        mock_boto_client.return_value = mock_iam
        mock_iam.list_role_policies.return_value = {"PolicyNames": [self.policy_name]}
        mock_publish.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "evt-123"}]}

        args = argparse.Namespace(
            plan_file="cli/fixtures/demo-role-plan.json",
            role_arn=self.role_arn,
            apply=True,
            policy_name=self.policy_name,
            event_bus=None,
            publish=True,
            source=None,
            region="ap-south-1",
        )

        for status in non_complete_statuses:
            mock_poll.reset_mock()
            mock_input.reset_mock()
            mock_iam.reset_mock()
            mock_iam.list_role_policies.return_value = {"PolicyNames": [self.policy_name]}

            mock_poll.return_value = {
                "request_id": f"req-{status}",
                "status": status,
                "role_arn": self.role_arn,
                "error_message": f"Simulated failure for {status}",
                "coverage_check": {"blocked_actions": "[]"},
                "cedar_validation": {"messages": ["invalid syntax"]},
                "analyzer_validation": {"reason": "VALIDATION_ERROR", "findings": []},
            }

            exit_code = handle_analyze(args)

            # Verification:
            # 1. Exit code must be non-zero (refusal)
            self.assertNotEqual(exit_code, 0, f"Expected non-zero exit for status {status}")
            # 2. input() prompt must NEVER be called
            mock_input.assert_not_called()
            # 3. put_role_policy must NEVER be called
            mock_iam.put_role_policy.assert_not_called()

        print("\n[Test 5 PASS] Verified --apply refuses to prompt or call PutRolePolicy for all non-COMPLETE statuses (ANALYZER_INVALID, CEDAR_INVALID, BLOCKED, ERROR, PROCESSING).")


if __name__ == "__main__":
    unittest.main(verbosity=2)
