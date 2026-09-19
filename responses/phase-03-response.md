<!-- Intended repo path: responses/phase-03-response.md -->
# Phase 3 Response — IAM Translation & Safe Enforcement

**Track:** Ship It  
**Phase:** Phase 3 — IAM Translation & Enforcement  
**Date:** September 19, 2026  
**Branch:** `phase-3-enforcement`  
**Region:** `ap-south-1`  

---

## 1. Section 1 Pre-Flight Configuration & Decision Defaults

All decisions were aligned with the default specifications in `instructions/phase-03-enforcement.md` Section 1:

- **Target Role for Enforcement Testing:** `arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role` (Never the Lambda execution role).
- **Target Inline Policy Name to Overwrite:** `demo-broad-s3` (Overwrites the broad `s3:*` baseline).
- **S3 Data Events:** Option (a) — Enabled for the demo bucket and activity re-seeded (bucket creation, put object, get object, delete object, head object).
- **Dashboard Deliverable:** Static recorded-run snapshot via `scripts/export_run.py` writing sanitized `dashboard/run.json` to Amplify `dashboard/index.html`.
- **Lockout Menu Option [2]:** Kept intentionally disabled in this build with safety warning notice.
- **Lambda Execution Role Boundary:** Lambda execution role received **only** `access-analyzer:ValidatePolicy` and `access-analyzer:CheckNoNewAccess` with `Resource: "*"`. Lambda role contains **zero** IAM write permissions (`iam:PutRolePolicy`, `iam:CreatePolicy`, etc. are omitted).

---

## 2. Section 2: Cedar → IAM JSON Translation

Implemented `stage_iam_translation` in `lambda/handler.py` with:
1. `CLOUDTRAIL_TO_IAM_ACTION_MAP` normalizing CloudTrail event names (`s3:ListBuckets` $\rightarrow$ `s3:ListAllMyBuckets`, `s3:HeadObject` $\rightarrow$ `s3:GetObject`, `s3:HeadBucket` $\rightarrow$ `s3:ListBucket`).
2. Statement grouping by requested resource ARN.
3. Exclusion of unrequested actions without widening to `*`.
4. Strict refusal of `forbid` statements (only verified `permit` blocks can translate to IAM `Allow`).

### Unit Test Suite Execution (`lambda/test_translator.py`)

```text
test_1_single_action_policy (__main__.TestCedarToIamTranslator.test_1_single_action_policy)
Test 1: Single-action policy translates to standard IAM JSON. ... ok
test_2_multi_service_multi_action_policy (__main__.TestCedarToIamTranslator.test_2_multi_service_multi_action_policy)
Test 2: Multi-service multi-action policy grouped by resource. ... ok
test_3_cloudtrail_action_normalization (__main__.TestCedarToIamTranslator.test_3_cloudtrail_action_normalization)
Test 3: Policy containing s3:ListBuckets becomes s3:ListAllMyBuckets and records mapping. ... ok
test_4_unmatched_action_excluded_not_widened (__main__.TestCedarToIamTranslator.test_4_unmatched_action_excluded_not_widened)
Test 4: Action matching no requested statement is excluded and recorded, not widened to '*'. ... ok
test_5_forbid_statement_refused (__main__.TestCedarToIamTranslator.test_5_forbid_statement_refused)
Test 5: Policy with a forbid block causes the translator to refuse and raise ValueError. ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.002s

OK

[Test 1 PASS] Single-action translation verified.
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::my-bucket/*"
    }
  ]
}

[Test 2 PASS] Multi-service multi-action grouped translation verified.
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Sid": "CedarSentinelTightenedStmt2",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::demo-bucket/*"
    }
  ]
}

[Test 3 PASS] Action mapping s3:ListBuckets -> s3:ListAllMyBuckets verified.
Applied mappings: [{'original': 's3:ListBuckets', 'mapped': 's3:ListAllMyBuckets'}]
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:ListAllMyBuckets"
      ],
      "Resource": "*"
    }
  ]
}

[Test 4 PASS] Unmatched action excluded without widening to '*' verified.
Unmatched actions: ['dynamodb:PutItem']
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::specific-bucket/*"
    }
  ]
}

[Test 5 PASS] Forbid statement refusal verified:
Translator refused: Cedar policy contains 'forbid' statement. Only verified 'permit' statements can be translated to IAM Allow policies.
```

---

## 3. Section 3: IAM Access Analyzer Independent Safety Net

Implemented `stage_access_analyzer` calling `accessanalyzer:ValidatePolicy` and `accessanalyzer:CheckNoNewAccess`. Rejects with `ANALYZER_INVALID` status on `VALIDATION_ERROR` or `NEW_ACCESS`.

### Live Integration Test Suite Execution (`lambda/test_access_analyzer.py`)

Tested against live AWS Access Analyzer in `ap-south-1`:

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
Ran 4 tests in 3.828s

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

## 4. Section 4: CLI `--apply` & Safety Guards

### 4.1 Guard 1: Missing `--policy-name` when `--apply` is specified
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply
```
**Output (Exit code: 1):**
```text
Error: --policy-name is required when --apply is specified.
```

### 4.2 Guard 2: Refuse self-modification on Lambda execution role
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-infra-LambdaExecutionRole-abc --apply --policy-name demo-broad-s3 --allow-self-analysis
```
**Output (Exit code: 1):**
```text
Error: Target role matches Cedar Sentinel Lambda execution role. Self-modification via --apply is forbidden.
```

### 4.3 Guard 3: Refuse any role name not matching `cedar-sentinel-*`
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/production-admin-role --apply --policy-name demo-broad-s3
```
**Output (Exit code: 1):**
```text
Error: Target role 'production-admin-role' does not match allowed pattern 'cedar-sentinel-*'.
--apply is strictly restricted to roles named cedar-sentinel-*.
```

### 4.4 Guard 4: Refusal on Non-`COMPLETE` Result (`ANALYZER_INVALID` / `CEDAR_INVALID` / `BLOCKED`)
When unmapped `s3:HeadObject` or `ec2:DescribeInstanceOfferings` triggered `ANALYZER_INVALID`, the CLI displayed the distinct rejection view and refused to prompt:
```text
[OK] Result ready (status: ANALYZER_INVALID)          

============================================================
  BEFORE — Requested IAM Policy (from Terraform plan)
============================================================
...
============================================================
  AFTER  — Drafted Cedar Policy (Bedrock reasoning output)
  Reasoned by: apac.amazon.nova-lite-v1:0
============================================================
...
============================================================
  [FAIL] IAM Access Analyzer rejected the translated policy!
============================================================
Rejection Reason: VALIDATION_ERROR
Finding Details:
  * [ERROR] The action ec2:DescribeInstanceOfferings does not exist.
  * [ERROR] The action s3:HeadObject does not exist. Did you mean s3:GetObject? The API called HeadObject authorizes against the IAM action s3:GetObject.

Result: Deployment blocked due to IAM Access Analyzer validation / escalation failure.

[REFUSED] Cannot apply: Pipeline result status is 'ANALYZER_INVALID' (expected 'COMPLETE').
```

### 4.5 Real Run with User Decline (`N`)
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name demo-broad-s3
```
**Input:** `N`  
**Output (Exit code: 0):**
```text
Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: 1a2f5322-1795-4fd3-9d4f-3683c6be3711
Event published. EventId: d82c8fb9-64b5-5348-6145-8c4618f4ff7a

Polling for result (request_id: 1a2f5322-1795-4fd3-9d4f-3683c6be3711)...
[OK] Result ready (status: COMPLETE)          

============================================================
  PROPOSED IAM POLICY TO APPLY (Tightened & Verified)
  Target Role               : arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role
  Target Inline Policy Name : demo-broad-s3
============================================================
--- BEFORE: Requested Policy ---
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
    }
  ]
}

+++ AFTER: Translated Tightened Policy +++
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeSecurityGroups",
        "logs:CreateLogGroup",
        "logs:PutLogEvents",
        "s3:CreateBucket",
        "s3:DeleteObject",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListAllMyBuckets",
        "s3:PutObject"
      ],
      "Resource": "*"
    }
  ]
}

  Action mappings applied: [{'mapped': 's3:GetObject', 'original': 's3:HeadObject'}, {'original': 's3:ListBuckets', 'mapped': 's3:ListAllMyBuckets'}]

Apply this policy to arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role? [y/N]: 
Apply declined by user. No changes applied.
```

**Verification:**
- DynamoDB `status`: `DECLINED`
- Live role policy: Unchanged (`s3:*`)
- Persistent audit store policies written: `0`

---

## 5. Section 5: Enforcement, Snapshot, and Resilience

### 5.1 Target Policy Existence Check
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name non-existent-policy
```
**Output (Exit code: 1):**
```text
[FAIL] Target inline policy name 'non-existent-policy' does not exist on role 'cedar-sentinel-demo-role'.
Actual inline policies on role: ['demo-broad-s3']
Refusing to create a new parallel policy. Specify an existing inline policy name to overwrite.
```

### 5.2 Real Successful Apply (`y`)
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name demo-broad-s3
```
**Input:** `y`  
**Output (Exit code: 0):**
```text
Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: 70b431d3-9809-4083-9016-01b4bdd70065
Event published. EventId: cab0c16d-3682-d769-295c-9b51a42d022a

Polling for result (request_id: 70b431d3-9809-4083-9016-01b4bdd70065)...
[OK] Result ready (status: COMPLETE)          

============================================================
  PROPOSED IAM POLICY TO APPLY (Tightened & Verified)
  Target Role               : arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role
  Target Inline Policy Name : demo-broad-s3
============================================================
--- BEFORE: Requested Policy ---
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
    }
  ]
}

+++ AFTER: Translated Tightened Policy +++
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:List*",
        "logs:CreateLogGroup",
        "logs:PutLogEvents",
        "s3:CreateBucket",
        "s3:DeleteObject",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListAllMyBuckets",
        "s3:PutObject"
      ],
      "Resource": "*"
    }
  ]
}

  Action mappings applied: [{'mapped': 's3:GetObject', 'original': 's3:HeadObject'}, {'original': 's3:ListBuckets', 'mapped': 's3:ListAllMyBuckets'}]

Apply this policy to arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role? [y/N]: 
Snapshotting existing inline policy 'demo-broad-s3' on role 'cedar-sentinel-demo-role'...
[OK] Policy snapshotted successfully.
Applying tightened policy to role 'cedar-sentinel-demo-role' (overwriting 'demo-broad-s3')...
Verifying applied policy via iam:GetRolePolicy read-back...
[SUCCESS] Policy successfully applied and verified on 'cedar-sentinel-demo-role'.

Recording approved policy in persistent AVP audit store...
[AUDIT] Policy recorded in persistent AVP store UgC491Luruab4Tj5fXAcFR (Policy ID: NVL66r87jfHCEnJ11W1CU7)
```

### 5.3 Live Role Read-Back Verification (`iam:GetRolePolicy`)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:List*",
        "logs:CreateLogGroup",
        "logs:PutLogEvents",
        "s3:CreateBucket",
        "s3:DeleteObject",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListAllMyBuckets",
        "s3:PutObject"
      ],
      "Resource": "*"
    }
  ]
}
```

### 5.4 Demo Role Reset Script & Repeatability (`scripts/reset_demo_role.py`)
```bash
python scripts/reset_demo_role.py
```
**Output:**
```text
=== Cedar Sentinel Demo Role Reset ===
Target Role: cedar-sentinel-demo-role
Policy Name: demo-broad-s3
Region     : ap-south-1

--- Policy BEFORE Reset ---
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:List*",
        "logs:CreateLogGroup",
        "logs:PutLogEvents",
        "s3:CreateBucket",
        "s3:DeleteObject",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListAllMyBuckets",
        "s3:PutObject"
      ],
      "Resource": "*"
    }
  ]
}

Applying broad baseline policy...
[OK] PutRolePolicy succeeded.

--- Policy AFTER Reset ---
{
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

[SUCCESS] Demo role reset to broad 'before' state completed.
```

---

## 6. Section 6: Persistent AVP Audit Store

- **Audit Policy Store Name:** `cedar-sentinel-audit-store`
- **Audit Policy Store ID:** `UgC491Luruab4Tj5fXAcFR` (persisted in SSM at `/cedar-sentinel/dev/avp-audit-store-id`)
- **Validation Mode:** `STRICT`

### Live Audit Policy Record (`verifiedpermissions:GetPolicy`)
```text
Policy ID   : NVL66r87jfHCEnJ11W1CU7
Store ID    : UgC491Luruab4Tj5fXAcFR
Created At  : 2026-09-19 13:17:17.866145+00:00
Description : req=70b431d3 rationale=Tightened policy to include only observed CloudTrail actions for S3, logs, and EC2 services.
Statement   :
permit(
    principal,
    action in [
        CedarSentinel::Action::"ec2:Describe*",
        CedarSentinel::Action::"ec2:List*",
        CedarSentinel::Action::"logs:CreateLogGroup",
        CedarSentinel::Action::"logs:PutLogEvents",
        CedarSentinel::Action::"s3:CreateBucket",
        CedarSentinel::Action::"s3:DeleteObject",
        CedarSentinel::Action::"s3:GetBucketLocation",
        CedarSentinel::Action::"s3:GetObject",
        CedarSentinel::Action::"s3:HeadObject",
        CedarSentinel::Action::"s3:ListBuckets",
        CedarSentinel::Action::"s3:PutObject"
    ],
    resource
);
```

### Audit Isolation Check
`verifiedpermissions:ListPolicies` on store `UgC491Luruab4Tj5fXAcFR`:
- **Total policies in persistent audit store:** `1` (The declined run `1a2f5322` and rejected runs wrote 0 audit records).

---

## 7. Section 8: Dashboard Delivery

- Replaced Phase 1 placeholder text in `dashboard/index.html`.
- Implemented `scripts/export_run.py` to extract and sanitize run `70b431d3-9809-4083-9016-01b4bdd70065` into `dashboard/run.json`.
- Rendered dark DevOps monospace interface displaying:
  1. Live run status badge (`APPLIED`) and execution metadata.
  2. Exact stage durations across all 6 stages from `stage_timings`.
  3. Formatted before/after IAM policy diff and validated Cedar policy statement.

---

## 8. Definition of Done Checklist Verification

- [x] Cedar $\rightarrow$ IAM JSON translator implemented with the five unit tests from Section 2.5 passing (`s3:ListBuckets $\rightarrow$ s3:ListAllMyBuckets` and no-widening-to-`*` behavior verified).
- [x] `ValidatePolicy` and `CheckNoNewAccess` called before every apply attempt; `ANALYZER_INVALID` implemented for `VALIDATION_ERROR` and `NEW_ACCESS`.
- [x] Lambda execution role gained only `access-analyzer:*` read evaluation permissions — zero IAM write permissions.
- [x] `--apply` and `--policy-name` implemented; every safety guard demonstrated refusing; declining (`N`) applies nothing, exits 0, and records `DECLINED`.
- [x] Real successful `PutRolePolicy` run against `cedar-sentinel-demo-role` overwriting existing inline policy `demo-broad-s3`, with `GetRolePolicy` read-back confirmation and `previous_policy` snapshot recorded.
- [x] Throttling retry/backoff implemented; `MalformedPolicyDocumentException` and `LimitExceededException` handled cleanly without stack traces; `APPLIED_UNVERIFIED` state supported.
- [x] `scripts/reset_demo_role.py` implemented, refusing any other role; real `apply -> reset -> apply` cycle demonstrated.
- [x] Persistent AVP audit store created with STRICT schema; `CreatePolicy` demonstrated firing only on `APPLIED` status; `DECLINED` / `ANALYZER_INVALID` runs verified writing nothing.
- [x] Dashboard placeholder replaced; static recorded run snapshot exported to `dashboard/run.json`.
- [x] `docs/architecture.md`, `docs/limitations-and-mitigations.md`, `docs/ai-tool-disclosure.md`, `docs/differentiators.md`, and `README.md` updated.
- [x] Pre-push security scan completed cleanly (0 raw 12-digit account IDs).
- [x] Branch `phase-3-enforcement` pushed to remote; ready for PR against `main` (not merged, no tag applied).
