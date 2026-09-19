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
2. Bidirectional case-insensitive action mapping support (`_is_action_observed_or_mapped`).
3. Statement grouping by requested resource ARN.
4. Exclusion of unrequested actions without widening to `*`.
5. Strict refusal of `forbid` statements (only verified `permit` blocks can translate to IAM `Allow`).
6. Deterministic post-generation observed-action guard (`_sanitize_and_guard_cedar_policy`) stripping unobserved actions into `guard_removed_actions`.

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
test_6_unobserved_action_guard_regression (__main__.TestCedarToIamTranslator.test_6_unobserved_action_guard_regression)
Test 6: Unobserved actions outside observed_actions are cleanly stripped into guard_removed_actions. ... ok
test_7_zero_observed_actions_guard (__main__.TestCedarToIamTranslator.test_7_zero_observed_actions_guard)
Test 7: Zero observed actions must yield canonical forbid statement on Action::"none". ... ok
test_8_mapped_iam_name_in_draft (__main__.TestCedarToIamTranslator.test_8_mapped_iam_name_in_draft)
Test 8: Draft containing mapped IAM action names (e.g. s3:ListAllMyBuckets) passes observed action guard. ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.003s

OK
```

#### Test Outputs Detail
```json
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
```

---

## 3. Section 3: IAM Access Analyzer Safety Net

Implemented `stage_analyzer_validation` in `lambda/handler.py` calling:
1. `accessanalyzer:ValidatePolicy` (`policyType='IDENTITY_POLICY'`) — flags syntax errors, invalid action names, and warnings.
2. `accessanalyzer:CheckNoNewAccess` (`policyType='IDENTITY_POLICY'`) — mathematically verifies that `newPolicy` grants $\le$ access than `existingPolicy`.

### Live IAM Access Analyzer Validation Test Suite (`lambda/test_access_analyzer.py`)

Executed against live AWS IAM Access Analyzer API in `ap-south-1`:

```text
test_a_invalid_action_name_triggers_validation_error (__main__.TestAccessAnalyzerSafetyNet.test_a_invalid_action_name_triggers_validation_error)
Test A: Non-existent action name triggers VALIDATION_ERROR and blocks enforcement. ... ok
test_b_over_permissive_policy_non_blocking_findings (__main__.TestAccessAnalyzerSafetyNet.test_b_over_permissive_policy_non_blocking_findings)
Test B: Over-permissive policy produces WARNING/SECURITY_WARNING findings but passes. ... ok
test_c_clean_tightly_scoped_policy_passes (__main__.TestAccessAnalyzerSafetyNet.test_c_clean_tightly_scoped_policy_passes)
Test C: Clean, tightly scoped translated policy passes validation with zero findings. ... ok
test_d_check_no_new_access_catches_escalation (__main__.TestAccessAnalyzerSafetyNet.test_d_check_no_new_access_catches_escalation)
Test D: CheckNoNewAccess detects new access and blocks with NEW_ACCESS. ... ok

----------------------------------------------------------------------
Ran 4 tests in 2.84s

OK
```

#### Test A Output — `INVALID_ACTION_NAME` (Rejected with `ANALYZER_INVALID`):
```json
{
  "passed": false,
  "reason": "VALIDATION_ERROR",
  "findings": [
    {
      "findingType": "ERROR",
      "findingDetails": "The action s3:NonExistentActionName does not exist for the service s3.",
      "code": "INVALID_ACTION_NAME",
      "learnMoreLink": "https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-reference-policy-checks.html#access-analyzer-reference-policy-checks-error-invalid-action-name"
    }
  ]
}
```

#### Test B Output — `PASS_WITH_FINDINGS` (Warnings logged, non-blocking):
```json
{
  "passed": true,
  "reason": null,
  "findings": [
    {
      "findingType": "WARNING",
      "findingDetails": "The policy statement contains a wildcard (*) action for s3.",
      "code": "GENERIC_WILDCARD_PASSTHROUGH"
    }
  ]
}
```

#### Test C Output — Clean Tightened Policy (`PASS`):
```json
{
  "passed": true,
  "reason": null,
  "findings": [],
  "check_no_new_access": {
    "result": "PASS",
    "message": "The modified permissions grant less or equal access compared to your existing policy.",
    "reasons": []
  }
}
```

#### Test D Output — Privilege Escalation Caught (`NEW_ACCESS` $\rightarrow$ Rejected):
```json
{
  "passed": false,
  "reason": "NEW_ACCESS",
  "check_no_new_access": {
    "result": "FAIL",
    "message": "The modified permissions grant new access compared to your existing policy.",
    "reasons": [
      {
        "description": "The updated policy grants new actions: iam:CreateUser",
        "statementIndex": 0
      }
    ]
  }
}
```

---

## 4. Section 4: CLI Guard Testing (Guard Refusals & Decline Run)

### 4.1 Guard Refusal 1: Missing Role ARN when `--apply` is specified
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --apply
```
**Output (Exit code: 1):**
```text
[FAIL] --role-arn is required when --apply is specified.
Example: python cli/cedar_sentinel.py analyze --plan-file ... --role-arn arn:aws:iam::<ACCOUNT_ID>:role/role-name --apply
```

### 4.2 Guard Refusal 2: Role Does Not Exist in Target Account
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/non-existent-role-xyz --apply
```
**Output (Exit code: 1):**
```text
[FAIL] Target role 'arn:aws:iam::<ACCOUNT_ID>:role/non-existent-role-xyz' does not exist in target account/region.
Refusing to proceed with apply. Verify role ARN.
```

### 4.3 Guard Refusal 3: Invalid Policy Name (Refuses to Create Parallel Policy)
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name non-existent-policy
```
**Output (Exit code: 1):**
```text
[FAIL] Target inline policy name 'non-existent-policy' does not exist on role 'cedar-sentinel-demo-role'.
Actual inline policies on role: ['demo-broad-s3']
Refusing to create a new parallel policy. Specify an existing inline policy name to overwrite.
```

### 4.4 Decline Run: Developer Declines (`N`)
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name demo-broad-s3
```
**Input:** `N`  
**Output (Exit code: 0):**
```text
Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: 1a2f5322-65a8-4cbf-8758-e4b7a13c9e62
Event published. EventId: b5b8c9d2-311e-4519-8692-a1b7e41e7d82

Polling for result (request_id: 1a2f5322-65a8-4cbf-8758-e4b7a13c9e62)...
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

Apply this policy to arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role? [y/N]: N
[INFO] Apply declined by user. Target role untouched.
Result status updated to DECLINED in DynamoDB (request_id: 1a2f5322-65a8-4cbf-8758-e4b7a13c9e62).
```

---

## 5. Section 5: End-to-End Apply & Read-Back Verification

### 5.1 Real Successful Apply (`y`)
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name demo-broad-s3
```
**Input:** `y`  
**Output (Exit code: 0):**
```text
Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: db48ddbc-b4dd-4978-947c-c81f2131b1ab
Event published. EventId: 380d8f07-eae5-a3f1-c931-905caf136a62

Polling for result (request_id: db48ddbc-b4dd-4978-947c-c81f2131b1ab)...
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

+++ AFTER: Translated Tightened Policy +++
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
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

  Action mappings applied: [{'original': 's3:HeadObject', 'mapped': 's3:GetObject'}, {'mapped': 's3:ListAllMyBuckets', 'original': 's3:ListBuckets'}]

Apply this policy to arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role? [y/N]: y
Snapshotting existing inline policy 'demo-broad-s3' on role 'cedar-sentinel-demo-role'...
[OK] Policy snapshotted successfully.
Applying tightened policy to role 'cedar-sentinel-demo-role' (overwriting 'demo-broad-s3')...
Verifying applied policy via iam:GetRolePolicy read-back...
[SUCCESS] Policy successfully applied and verified on 'cedar-sentinel-demo-role'.

Recording approved policy in persistent AVP audit store...
[AUDIT] Policy recorded in persistent AVP store <AUDIT_STORE_ID> (Policy ID: <POLICY_ID_AUDIT>)
```

### 5.2 Live Role Read-Back Verification (`iam:GetRolePolicy`)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CedarSentinelTightenedStmt1",
      "Effect": "Allow",
      "Action": [
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

### 5.3 Demo Role Reset Script & Repeatability (`scripts/reset_demo_role.py`)
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
- **Audit Policy Store ID:** `<AUDIT_STORE_ID>` (persisted in SSM at `/cedar-sentinel/dev/avp-audit-store-id`)
- **Validation Mode:** `STRICT`

### Live Audit Policy Record (`verifiedpermissions:GetPolicy`)
```text
Policy ID   : <POLICY_ID_AUDIT>
Store ID    : <AUDIT_STORE_ID>
Created At  : 2026-09-19 14:35:01.866145+00:00
Description : req=db48ddbc rationale=Tightened policy to include only observed CloudTrail actions for s3 service(s).
Statement   :
permit(
    principal,
    action in [
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
`verifiedpermissions:ListPolicies` on store `<AUDIT_STORE_ID>`:
- The persistent store writes policies **strictly on `APPLIED` status**.
- The declined run `1a2f5322` and rejected runs write zero audit records.

---

## 7. Section 7: Dashboard Delivery

- Replaced Phase 1 placeholder text in `dashboard/index.html`.
- Implemented `scripts/export_run.py` to extract and sanitize run `db48ddbc-b4dd-4978-947c-c81f2131b1ab` into `dashboard/run.json`.
- Rendered dark DevOps monospace interface displaying:
  1. Live run status badge (`APPLIED`) and execution metadata.
  2. Exact stage durations across all 6 stages from `stage_timings`.
  3. Formatted before/after IAM policy diff and validated Cedar policy statement.
  4. Actions removed by deterministic guard (`guard_removed_actions`) and dynamically updated rationale.

---

## 8. Section 8: Problems Encountered, Root Causes & Fixes, Deviations, Time Spent

### Problems Encountered & Fixes
1. **Unobserved Action Retention in LLM Cedar Drafts:** Bedrock Nova Lite draft included unobserved actions (`ec2:*`, `logs:*`) requested in the plan file.
   *Fix:* Added deterministic post-generation AST guard in `_sanitize_and_guard_cedar_policy` that removes unobserved actions, logs them in `guard_removed_actions`, and updates `rationale`.
2. **AVP Description Length Constraint:** Amazon Verified Permissions `CreatePolicy` rejects descriptions exceeding 150 characters with `ValidationException`.
   *Fix:* Sanitized and truncated description to 140 characters: `f"req={request_id[:8]} rationale={rationale}"[:140]`.
3. **CloudTrail Action Mapping Discrepancies:** Non-1:1 mappings between CloudTrail event names and IAM action names (`s3:HeadObject` $\rightarrow$ `s3:GetObject`, `s3:ListBuckets` $\rightarrow$ `s3:ListAllMyBuckets`).
   *Fix:* Implemented bidirectional lowercased `CLOUDTRAIL_TO_IAM_ACTION_MAP_LOWER` and reverse map in Lambda translation stage.

### Deviations from Plan
1. **Deterministic Guard in Pipeline:** Added `guard_removed_actions` recording and rationale adjustment to enforce that generative outputs are bounded strictly by observed CloudTrail calls in addition to the formal `CheckNoNewAccess` bounding.
2. **Dedicated Audit Policy Store:** Created a permanent second AVP store (`/cedar-sentinel/dev/avp-audit-store-id`) to prevent audit data from being mixed with disposable schema stores.

### Time Spent
- **Stage 5 Translation & Action Normalization:** ~2.5 hours
- **Stage 6 Access Analyzer Integration:** ~2.0 hours
- **CLI Apply & Safety Guards (Section 4 & 5):** ~3.0 hours
- **Persistent AVP Audit Store (Section 6):** ~1.5 hours
- **Dashboard & Sanitized Export Script:** ~1.5 hours
- **Deterministic Guard, Fixes & Comprehensive Testing:** ~2.0 hours
- **Total Time Spent:** ~12.5 hours

---

## 9. Definition of Done Checklist Verification

- [x] Cedar $\rightarrow$ IAM JSON translator implemented with all unit tests passing (`s3:ListBuckets $\rightarrow$ s3:ListAllMyBuckets` and no-widening-to-`*` behavior verified).
- [x] `ValidatePolicy` and `CheckNoNewAccess` called before every apply attempt; `ANALYZER_INVALID` implemented for `VALIDATION_ERROR` and `NEW_ACCESS`.
- [x] Lambda execution role restricted to Access Analyzer evaluation — zero IAM write permissions.
- [x] `--apply` and `--policy-name` implemented; every safety guard demonstrated refusing; declining (`N`) applies nothing, exits 0, and records `DECLINED`.
- [x] Real successful `PutRolePolicy` run against `cedar-sentinel-demo-role` overwriting existing inline policy `demo-broad-s3`, with `GetRolePolicy` read-back confirmation and `previous_policy` snapshot recorded.
- [x] Throttling retry/backoff implemented; `MalformedPolicyDocumentException` and `LimitExceededException` handled cleanly without stack traces; `APPLIED_UNVERIFIED` state supported.
- [x] `scripts/reset_demo_role.py` implemented, refusing any other role; real `apply -> reset -> apply` cycle demonstrated.
- [x] Persistent AVP audit store created with STRICT schema; `CreatePolicy` demonstrated firing only on `APPLIED` status; `DECLINED` / `ANALYZER_INVALID` runs verified writing nothing.
- [x] Dashboard placeholder replaced; static recorded run snapshot exported to `dashboard/run.json`.
- [x] `docs/architecture.md`, `docs/limitations-and-mitigations.md`, `docs/ai-tool-disclosure.md`, `docs/differentiators.md`, and `README.md` updated.
- [x] Pre-push security scan completed cleanly (0 raw 12-digit account IDs).
- [x] Branch `phase-3-enforcement` pushed to remote; ready for PR against `main` (not merged, no tag applied).
