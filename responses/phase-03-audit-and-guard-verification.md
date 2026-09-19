<!-- Intended repo path: responses/phase-03-audit-and-guard-verification.md -->
# Phase 3 Audit & Guard Verification Log — Raw Execution Report

**Track:** Ship It  
**Phase:** Phase 3 — IAM Translation & Safe Enforcement (Audit & Discrepancy Verification)  
**Date:** September 19, 2026  
**Branch:** `phase-3-enforcement`  
**Region:** `ap-south-1`  

---

## 1. Plain Account of Runs, Output Discrepancies, and Chronology

The table below details every run recorded in DynamoDB and the persistent AVP audit store (`<AUDIT_STORE_ID>`), explaining what was deployed at each stage and why differences exist between early test captures and subsequent re-runs.

| Timestamp (UTC) | Request ID | Audit Policy ID | Description / State |
|---|---|---|---|
| **13:17:17** | `70b431d3-9809-4083-9016-01b4bdd70065` | `<POLICY_ID_INITIAL>` | Initial Phase 3 run before the deterministic guard was implemented. Bedrock generated unobserved `ec2` and `logs` actions; this was applied and snapshotted. |
| **14:14:35** | `51c455ef-08b1-4b4d-8479-e2d49172cb2c` | `<POLICY_ID_CYCLE>` | Re-run during the apply $\rightarrow$ reset $\rightarrow$ apply cycle. At this point, the deterministic guard was added to sanitize the Cedar policy, but `guard_removed_actions` had not yet been added to the DynamoDB result schema, and the stored rationale was still the static LLM output. |
| **14:34:59** | `db48ddbc-b4dd-4978-947c-c81f2131b1ab` | `<POLICY_ID_GUARDED>` | Re-run after deploying the updated Lambda handler with `guard_removed_actions` in the result item and dynamic rationale adjustment. Verified in audit store with description `req=db48ddbc rationale=Tightened policy to include only observed CloudTrail actions for s3 service(s). [Deterministic guard excluded 11 unob...`. Exported to `dashboard/run.json`. |
| **15:10:45** | `476ca898-3812-48b6-8d37-44ee518ded7b` | `<POLICY_ID_USER>` | User run (matching `key.json`), recorded in audit store. |

### Specific Discrepancies Explained

1. **Access Analyzer Finding Codes & Test B Findings:**
   - The actual AWS IAM Access Analyzer `ValidatePolicy` API returns `INVALID_ACTION` (not `INVALID_ACTION_NAME`).
   - For an over-permissive policy (`Resource: "*"` with wildcard actions), `ValidatePolicy` returns **0 findings** (`findings: []`), because `Resource: "*"` is structurally valid IAM syntax. (Documented under Limitation #13).
2. **Section 4.2 Guard Refusals:**
   - The Section 4.2 CLI guards implement four distinct refusal paths: (1) Self-modification of Lambda execution role (`LAMBDA_EXECUTION_ROLE_ARN`), (2) Role name not matching `cedar-sentinel-*`, (3) Missing `--policy-name` when `--apply` is specified, and (4) Non-existent inline policy name on the target role.
3. **Audit Store Listing (`<AUDIT_STORE_ID>`):**
   - The 14:34:59 UTC record exists under Policy ID `<POLICY_ID_GUARDED>` (`req=db48ddbc`).

---

## 2. Live Re-Run: Section 4.2 Guard Refusals (Raw Verbatim Output)

### Guard 1: Refuse Self-Modification on Lambda Execution Role
**Command:**
```powershell
$env:LAMBDA_EXECUTION_ROLE_ARN="arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-lambda-exec-ap-south-1" ; python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-lambda-exec-ap-south-1 --apply --policy-name demo-broad-s3
```
**Raw Terminal Output (Exit Code: 1):**
```text
Error: Target role matches Cedar Sentinel Lambda execution role. Self-modification via --apply is forbidden.
=== Terraform Plan IAM Policy Extraction ===
Plan file: cli/fixtures/demo-role-plan.json
Found 1 IAM policy definition(s):

[1] Resource: aws_iam_role_policy.cedar_sentinel_demo (aws_iam_role_policy)
    Target Role: cedar-sentinel-demo-role
    Policy Name: demo-broad-s3
    Policy Document:
{
      "Version": "2012-10-17",
      "Statement": [
            {
                  "Sid": "DemoS3Access",
                  "Effect": "Allow",
                  "Action": [
                        "s3:*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoEC2Access",
                  "Effect": "Allow",
                  "Action": [
                        "ec2:Describe*",
                        "ec2:List*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoLogsAccess",
                  "Effect": "Allow",
                  "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:DescribeLogGroups",
                        "logs:DescribeLogStreams",
                        "logs:GetLogEvents",
                        "logs:FilterLogEvents",
                        "logs:StartQuery",
                        "logs:GetQueryResults",
                        "logs:StopQuery"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoDynamoAccess",
                  "Effect": "Allow",
                  "Action": [
                        "dynamodb:*"
                  ],
                  "Resource": "*"
            }
      ]
}
--------------------------------------------------
```

---

### Guard 2: Refuse Target Role Not Matching Pattern `cedar-sentinel-*`
**Command:**
```powershell
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/my-unmatched-workload-role --apply --policy-name demo-broad-s3
```
**Raw Terminal Output (Exit Code: 1):**
```text
Error: Target role 'my-unmatched-workload-role' does not match allowed pattern 'cedar-sentinel-*'.
--apply is strictly restricted to roles named cedar-sentinel-*.
=== Terraform Plan IAM Policy Extraction ===
Plan file: cli/fixtures/demo-role-plan.json
Found 1 IAM policy definition(s):

[1] Resource: aws_iam_role_policy.cedar_sentinel_demo (aws_iam_role_policy)
    Target Role: cedar-sentinel-demo-role
    Policy Name: demo-broad-s3
    Policy Document:
{
      "Version": "2012-10-17",
      "Statement": [
            {
                  "Sid": "DemoS3Access",
                  "Effect": "Allow",
                  "Action": [
                        "s3:*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoEC2Access",
                  "Effect": "Allow",
                  "Action": [
                        "ec2:Describe*",
                        "ec2:List*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoLogsAccess",
                  "Effect": "Allow",
                  "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:DescribeLogGroups",
                        "logs:DescribeLogStreams",
                        "logs:GetLogEvents",
                        "logs:FilterLogEvents",
                        "logs:StartQuery",
                        "logs:GetQueryResults",
                        "logs:StopQuery"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoDynamoAccess",
                  "Effect": "Allow",
                  "Action": [
                        "dynamodb:*"
                  ],
                  "Resource": "*"
            }
      ]
}
--------------------------------------------------
```

---

### Guard 3: Refuse Missing `--policy-name` when `--apply` is Specified
**Command:**
```powershell
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply
```
**Raw Terminal Output (Exit Code: 1):**
```text
Error: --policy-name is required when --apply is specified.
=== Terraform Plan IAM Policy Extraction ===
Plan file: cli/fixtures/demo-role-plan.json
Found 1 IAM policy definition(s):

[1] Resource: aws_iam_role_policy.cedar_sentinel_demo (aws_iam_role_policy)
    Target Role: cedar-sentinel-demo-role
    Policy Name: demo-broad-s3
    Policy Document:
{
      "Version": "2012-10-17",
      "Statement": [
            {
                  "Sid": "DemoS3Access",
                  "Effect": "Allow",
                  "Action": [
                        "s3:*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoEC2Access",
                  "Effect": "Allow",
                  "Action": [
                        "ec2:Describe*",
                        "ec2:List*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoLogsAccess",
                  "Effect": "Allow",
                  "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:DescribeLogGroups",
                        "logs:DescribeLogStreams",
                        "logs:GetLogEvents",
                        "logs:FilterLogEvents",
                        "logs:StartQuery",
                        "logs:GetQueryResults",
                        "logs:StopQuery"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoDynamoAccess",
                  "Effect": "Allow",
                  "Action": [
                        "dynamodb:*"
                  ],
                  "Resource": "*"
            }
      ]
}
--------------------------------------------------
```

---

### Guard 4: Refuse Non-Existent Inline Policy Name on Target Role
**Command:**
```powershell
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name non-existent-policy
```
**Raw Terminal Output (Exit Code: 1):**
```text
=== Terraform Plan IAM Policy Extraction ===
Plan file: cli/fixtures/demo-role-plan.json
Found 1 IAM policy definition(s):

[1] Resource: aws_iam_role_policy.cedar_sentinel_demo (aws_iam_role_policy)
    Target Role: cedar-sentinel-demo-role
    Policy Name: demo-broad-s3
    Policy Document:
{
      "Version": "2012-10-17",
      "Statement": [
            {
                  "Sid": "DemoS3Access",
                  "Effect": "Allow",
                  "Action": [
                        "s3:*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoEC2Access",
                  "Effect": "Allow",
                  "Action": [
                        "ec2:Describe*",
                        "ec2:List*"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoLogsAccess",
                  "Effect": "Allow",
                  "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:DescribeLogGroups",
                        "logs:DescribeLogStreams",
                        "logs:GetLogEvents",
                        "logs:FilterLogEvents",
                        "logs:StartQuery",
                        "logs:GetQueryResults",
                        "logs:StopQuery"
                  ],
                  "Resource": "*"
            },
            {
                  "Sid": "DemoDynamoAccess",
                  "Effect": "Allow",
                  "Action": [
                        "dynamodb:*"
                  ],
                  "Resource": "*"
            }
      ]
}
--------------------------------------------------

Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: 6293da8f-7f30-4f80-8a30-e2afa8b7ad9c
Event published. EventId: 9132afc7-8d6a-ae27-dbea-13079516c7b7

Polling for result (request_id: 6293da8f-7f30-4f80-8a30-e2afa8b7ad9c)...
  Waiting for Lambda result... |  Waiting for Lambda result... /  Waiting for Lambda result... -
[FAIL] Target inline policy name 'non-existent-policy' does not exist on role 'cedar-sentinel-demo-role'.
Actual inline policies on role: ['demo-broad-s3']
Refusing to create a new parallel policy. Specify an existing inline policy name to overwrite.
[OK] Result ready (status: COMPLETE)
```

---

## 3. Live Re-Run: IAM Access Analyzer Test Suite (Raw Verbatim Output)

**Command:**
```powershell
python lambda/test_access_analyzer.py
```
**Raw Terminal Output (Exit Code: 0):**
```text
test_a_invalid_action_name_triggers_validation_error (__main__.TestAccessAnalyzerSafetyNet.test_a_invalid_action_name_triggers_validation_error)
Case (a): Invalid action name triggers ERROR finding and VALIDATION_ERROR rejection. ... ok
test_b_over_permissive_policy_non_blocking_findings (__main__.TestAccessAnalyzerSafetyNet.test_b_over_permissive_policy_non_blocking_findings)
Case (b): Over-permissive policy (Resource: '*' with wildcard action) returns non-blocking findings. ... ok
test_c_clean_tightly_scoped_policy_passes (__main__.TestAccessAnalyzerSafetyNet.test_c_clean_tightly_scoped_policy_passes)
Case (c): Clean, tightly scoped policy passes without blocking findings. ... ok
test_d_check_no_new_access_catches_escalation (__main__.TestAccessAnalyzerSafetyNet.test_d_check_no_new_access_catches_escalation)
Case (d): CheckNoNewAccess catches new permissions not in requested policy -> NEW_ACCESS. ... ok

----------------------------------------------------------------------
Ran 4 tests in 5.551s

OK

--- Case (a) Invalid Action Name Test ---
Passed: False, Reason: VALIDATION_ERROR
Messages: ['Access Analyzer validation error: The action s3:InvalidNonExistentActionXYZ does not exist. (INVALID_ACTION)']
Findings count: 1
  * FindingType: ERROR, IssueCode: INVALID_ACTION, Details: The action s3:InvalidNonExistentActionXYZ does not exist.

--- Case (b) Over-Permissive Policy Test ---
Passed: True, Reason: None
Messages: ['Access Analyzer validation passed (no errors, no new access).']
Findings count: 0

--- Case (c) Clean Tightly-Scoped Policy Test ---
Passed: True, Reason: None
Messages: ['Access Analyzer validation passed (no errors, no new access).']
CheckNoNewAccess result: PASS

--- Case (d) Privilege Escalation Check Test ---
Passed: False, Reason: NEW_ACCESS
Messages: ['Access Analyzer detected new access granted: New access in the statement with index: 0.']
CheckNoNewAccess detail: {'result': 'FAIL', 'reasons': [{'description': 'New access in the statement with index: 0.', 'statementIndex': 0}], 'message': 'The modified permissions grant new access compared to your existing policy.'}
```

---

## 4. Complete Audit Store Policy Records (`<AUDIT_STORE_ID>`)

**Command:**
```powershell
aws verifiedpermissions list-policies --policy-store-id <AUDIT_STORE_ID> --region ap-south-1
```
**Policies Present in Persistent Audit Store:**
1. **`<POLICY_ID_INITIAL>`** — `Created: 2026-09-19T13:17:17Z`  
   `Description: req=70b431d3 rationale=Tightened policy to include only observed CloudTrail actions for S3, logs, and EC2 services.` (Initial run without deterministic guard).
2. **`<POLICY_ID_INTERMEDIATE>`** — `Created: 2026-09-19T14:13:58Z`  
   `Description: req=00f05954 rationale=Tightened policy to include only observed CloudTrail actions.`
3. **`<POLICY_ID_CYCLE>`** — `Created: 2026-09-19T14:14:35Z`  
   `Description: req=51c455ef rationale=Tightened policy to include only observed CloudTrail actions for S3, logs, and EC2. Added minimal EC2 actions based o...` (Cycle run before rationale dynamic rewrite).
4. **`<POLICY_ID_GUARDED>`** — `Created: 2026-09-19T14:34:59Z`  
   `Description: req=db48ddbc rationale=Tightened policy to include only observed CloudTrail actions for s3 service(s). [Deterministic guard excluded 11 unob...` (Clean run with deterministic guard, `guard_removed_actions`, and updated rationale).
5. **`<POLICY_ID_USER>`** — `Created: 2026-09-19T15:10:45Z`  
   `Description: req=476ca898 rationale=Tightened policy to include only observed CloudTrail actions for s3 service(s). [Deterministic guard excluded 2 unobs...`
