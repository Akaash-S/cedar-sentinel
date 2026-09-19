<!-- Intended repo path: responses/phase-03-fixes-response.md -->
# Phase 3 Fixes Response — Guard Enhancement & Deep Dive Verification

**Track:** Ship It  
**Phase:** Phase 3 — IAM Translation & Enforcement (Follow-Up Resolutions)  
**Date:** September 19, 2026  
**Branch:** `phase-3-enforcement`  
**Region:** `ap-south-1`  

---

## 1. Resolution of Investigation Items (Items 1 & 2)

### 1.1 DynamoDB Item Dump for Request `70b431d3-...` & Root Cause Analysis

#### Full Redacted DynamoDB Item
```json
{
  "request_id": "70b431d3-9809-4083-9016-01b4bdd70065",
  "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role",
  "status": "APPLIED",
  "model_used": "apac.amazon.nova-lite-v1:0",
  "ttl": "1790083029",
  "completed_at": "2026-09-19T13:17:09.730343+00:00",
  "requested_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"DemoS3Access\", \"Effect\": \"Allow\", \"Action\": [\"s3:*\"], \"Resource\": \"*\"}, {\"Sid\": \"DemoEC2Access\", \"Effect\": \"Allow\", \"Action\": [\"ec2:Describe*\", \"ec2:List*\"], \"Resource\": \"*\"}, {\"Sid\": \"DemoLogsAccess\", \"Effect\": \"Allow\", \"Action\": [\"logs:CreateLogGroup\", \"logs:CreateLogStream\", \"logs:PutLogEvents\", \"logs:DescribeLogGroups\", \"logs:DescribeLogStreams\", \"logs:GetLogEvents\", \"logs:FilterLogEvents\", \"logs:StartQuery\", \"logs:GetQueryResults\", \"logs:StopQuery\"], \"Resource\": \"*\"}, {\"Sid\": \"DemoDynamoAccess\", \"Effect\": \"Allow\", \"Action\": [\"dynamodb:*\"], \"Resource\": \"*\"}]}",
  "previous_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"DemoS3Access\", \"Effect\": \"Allow\", \"Action\": \"s3:*\", \"Resource\": \"*\"}]}",
  "observed_actions": {
    "s3:CreateBucket": "1",
    "s3:HeadObject": "1",
    "s3:PutObject": "1",
    "s3:DeleteObject": "1",
    "s3:ListBuckets": "2",
    "s3:GetBucketLocation": "2",
    "s3:GetObject": "1"
  },
  "cedar_policy": "permit(\n    principal,\n    action in [\n        CedarSentinel::Action::\"ec2:Describe*\",\n        CedarSentinel::Action::\"ec2:List*\",\n        CedarSentinel::Action::\"logs:CreateLogGroup\",\n        CedarSentinel::Action::\"logs:PutLogEvents\",\n        CedarSentinel::Action::\"s3:CreateBucket\",\n        CedarSentinel::Action::\"s3:DeleteObject\",\n        CedarSentinel::Action::\"s3:GetBucketLocation\",\n        CedarSentinel::Action::\"s3:GetObject\",\n        CedarSentinel::Action::\"s3:HeadObject\",\n        CedarSentinel::Action::\"s3:ListBuckets\",\n        CedarSentinel::Action::\"s3:PutObject\"\n    ],\n    resource\n);",
  "iam_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"CedarSentinelTightenedStmt1\", \"Effect\": \"Allow\", \"Action\": [\"ec2:Describe*\", \"ec2:List*\", \"logs:CreateLogGroup\", \"logs:PutLogEvents\", \"s3:CreateBucket\", \"s3:DeleteObject\", \"s3:GetBucketLocation\", \"s3:GetObject\", \"s3:ListAllMyBuckets\", \"s3:PutObject\"], \"Resource\": \"*\"}]}",
  "action_mappings_applied": [
    {
      "original": "s3:HeadObject",
      "mapped": "s3:GetObject"
    },
    {
      "original": "s3:ListBuckets",
      "mapped": "s3:ListAllMyBuckets"
    }
  ],
  "unmatched_actions": [],
  "coverage_check": {
    "blocked_actions": "[]",
    "passed": true
  },
  "cedar_validation": {
    "passed": true,
    "messages": [
      "Policy passed STRICT Cedar schema validation."
    ],
    "policy_store_id": "<AVP_STORE_ID>"
  },
  "analyzer_validation": {
    "findings": [],
    "reason": null,
    "passed": true,
    "check_no_new_access": {
      "reasons": [],
      "message": "The modified permissions grant less or equal access compared to your existing policy.",
      "result": "PASS"
    },
    "messages": [
      "Access Analyzer validation passed (no errors, no new access)."
    ]
  },
  "rationale": "Tightened policy to include only observed CloudTrail actions for S3, logs, and EC2 services.",
  "stage_timings": [
    {
      "stage": "cloudwatch_query",
      "start": "2026-09-19T13:17:05.568173+00:00",
      "end": "2026-09-19T13:17:07.870589+00:00"
    },
    {
      "stage": "bedrock_call",
      "start": "2026-09-19T13:17:07.871900+00:00",
      "end": "2026-09-19T13:17:09.032341+00:00"
    },
    {
      "stage": "coverage_check",
      "start": "2026-09-19T13:17:09.033515+00:00",
      "end": "2026-09-19T13:17:09.034003+00:00"
    },
    {
      "stage": "cedar_validation",
      "start": "2026-09-19T13:17:09.034015+00:00",
      "end": "2026-09-19T13:17:09.396995+00:00"
    },
    {
      "stage": "iam_translation",
      "start": "2026-09-19T13:17:09.409101+00:00",
      "end": "2026-09-19T13:17:09.409335+00:00"
    },
    {
      "stage": "analyzer_validation",
      "start": "2026-09-19T13:17:09.409345+00:00",
      "end": "2026-09-19T13:17:09.702429+00:00"
    }
  ]
}
```

#### Exact Documents Passed to `CheckNoNewAccess`
1. **`existingPolicyDocument` (`requested_policy` from plan fixture):**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DemoS3Access",
      "Effect": "Allow",
      "Action": ["s3:*"],
      "Resource": "*"
    },
    {
      "Sid": "DemoEC2Access",
      "Effect": "Allow",
      "Action": ["ec2:Describe*", "ec2:List*"],
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
      "Action": ["dynamodb:*"],
      "Resource": "*"
    }
  ]
}
```

2. **`newPolicyDocument` (`iam_policy` translated from Cedar):**
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

#### Why Neither Translator Nor CheckNoNewAccess Caught Them
1. **Translator's Exclusion Logic:** `stage_iam_translation` checks whether each action in the draft Cedar policy is covered by any `Statement` in the `requested_policy`. Because the input fixture `cli/fixtures/demo-role-plan.json` contained statements for `DemoEC2Access` (`ec2:Describe*`, `ec2:List*`) and `DemoLogsAccess` (`logs:CreateLogGroup`, etc.), the translator successfully matched `ec2:Describe*` and `logs:CreateLogGroup` to `Resource: "*"` from the plan statements, leaving `unmatched_actions: []`.
2. **Access Analyzer `CheckNoNewAccess`:** `CheckNoNewAccess` compares `newPolicyDocument` against `existingPolicyDocument` (`requested_policy`). Because the `newPolicyDocument` granted a strict subset of what was requested in the Terraform plan (e.g. `ec2:Describe*` is $\subseteq$ `ec2:Describe*` and `s3:GetObject` is $\subseteq$ `s3:*`), Access Analyzer correctly concluded that no privilege escalation occurred compared to the requested plan and returned `PASS`.
3. **The Root Cause:** CloudTrail observed **only S3 actions** for the role (`s3:CreateBucket`, `s3:HeadObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBuckets`, `s3:GetBucketLocation`, `s3:GetObject`). Bedrock saw the 4 statements in the prompt and hallucinated/retained `ec2` and `logs` actions in the draft Cedar policy. The previous guard in `_sanitize_and_guard_cedar_policy` checked for valid format but did not filter actions against `observed_actions`.

### 1.2 Deterministic Guard Implementation & Verification

#### Deterministic Guard in `lambda/handler.py`
Implemented `_is_action_observed_or_mapped` and integrated it directly into `_sanitize_and_guard_cedar_policy`:
```python
def _is_action_observed_or_mapped(action: str, observed_actions: Dict[str, Any]) -> bool:
    obs_set = {str(k).lower(): v for k, v in observed_actions.items() if int(v) > 0}
    act_lower = action.lower()

    if act_lower in obs_set:
        return True

    for obs in obs_set:
        mapped = CLOUDTRAIL_TO_IAM_ACTION_MAP.get(obs, obs).lower()
        if act_lower == mapped:
            return True
        if CLOUDTRAIL_TO_IAM_ACTION_MAP.get(act_lower, act_lower) == obs:
            return True
        if CLOUDTRAIL_TO_IAM_ACTION_MAP.get(act_lower, act_lower) == mapped:
            return True

    return False
```
Any action drafted by the LLM that is not in `observed_actions` is deterministically stripped before schema validation, translation, or enforcement.

#### Unit Regression Tests (`lambda/test_translator.py`)
Added `test_6_unobserved_action_guard_regression` and `test_7_zero_observed_actions_guard`.

```text
test_1_single_action_policy (__main__.TestCedarToIamTranslator.test_1_single_action_policy) ... ok
test_2_multi_service_multi_action_policy (__main__.TestCedarToIamTranslator.test_2_multi_service_multi_action_policy) ... ok
test_3_cloudtrail_action_normalization (__main__.TestCedarToIamTranslator.test_3_cloudtrail_action_normalization) ... ok
test_4_unmatched_action_excluded_not_widened (__main__.TestCedarToIamTranslator.test_4_unmatched_action_excluded_not_widened) ... ok
test_5_forbid_statement_refused (__main__.TestCedarToIamTranslator.test_5_forbid_statement_refused) ... ok
test_6_unobserved_action_guard_regression (__main__.TestCedarToIamTranslator.test_6_unobserved_action_guard_regression) ... ok
test_7_zero_observed_actions_guard (__main__.TestCedarToIamTranslator.test_7_zero_observed_actions_guard) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.002s

OK
```

---

## 2. Real Apply $\rightarrow$ Reset $\rightarrow$ Apply Cycle (Item 3)

### Step 1: Initial Reset of Demo Role
```bash
python scripts/reset_demo_role.py
```
```text
=== Cedar Sentinel Demo Role Reset ===
Target Role: cedar-sentinel-demo-role
Policy Name: demo-broad-s3
Region     : ap-south-1

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

### Step 2: First Apply Execution
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name demo-broad-s3
```
```text
Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: 00f05954-abb4-4691-a6b6-a1db58308ed1
Event published. EventId: 65716b81-48df-49d9-2e4a-eb9c71726689

Polling for result (request_id: 00f05954-abb4-4691-a6b6-a1db58308ed1)...
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
[AUDIT] Policy recorded in persistent AVP store <AUDIT_STORE_ID> (Policy ID: <POLICY_ID_1>)
```

### Step 3: Intermediate Reset
```bash
python scripts/reset_demo_role.py
```
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

### Step 4: Second Apply Execution (Produces Second Audit Record)
```bash
python cli/cedar_sentinel.py analyze --plan-file cli/fixtures/demo-role-plan.json --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role --apply --policy-name demo-broad-s3
```
```text
Publishing analysis event to EventBridge bus 'cedar-sentinel-events'...
Request ID: 51c455ef-08b1-4b4d-8479-e2d49172cb2c
Event published. EventId: 8da6eaa6-27ff-ffcd-308e-8f0baa0ea898

Polling for result (request_id: 51c455ef-08b1-4b4d-8479-e2d49172cb2c)...
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
[AUDIT] Policy recorded in persistent AVP store <AUDIT_STORE_ID> (Policy ID: <POLICY_ID_2>)
```

#### Verification of Persistent Audit Store
Listing policies in store `<AUDIT_STORE_ID>` confirms multiple audit records were written:
```text
Total audit policies in store: 3
 - ID: <POLICY_ID_1> Created: 2026-09-19 14:13:58.951854+00:00
 - ID: <POLICY_ID_2> Created: 2026-09-19 14:14:35.360511+00:00
 - ID: <POLICY_ID_INITIAL> Created: 2026-09-19 13:17:17.866145+00:00
```

---

## 3. IAM Inspection & Previous Policy Snapshot (Item 4)

### 3.1 `ListRolePolicies` on Target Role
```json
{
  "PolicyNames": [
    "demo-broad-s3"
  ],
  "IsTruncated": false
}
```

### 3.2 `ListAttachedRolePolicies` on Target Role
```json
{
  "AttachedPolicies": [],
  "IsTruncated": false
}
```

### 3.3 `GetRolePolicy` on Target Role After Apply
```json
{
  "RoleName": "cedar-sentinel-demo-role",
  "PolicyName": "demo-broad-s3",
  "PolicyDocument": {
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
}
```

### 3.4 `previous_policy` Snapshot from DynamoDB Result Item
```json
{
  "request_id": "51c455ef-08b1-4b4d-8479-e2d49172cb2c",
  "status": "APPLIED",
  "other_policies": null,
  "previous_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"DemoS3Access\", \"Effect\": \"Allow\", \"Action\": \"s3:*\", \"Resource\": \"*\"}]}",
  "iam_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"CedarSentinelTightenedStmt1\", \"Effect\": \"Allow\", \"Action\": [\"s3:CreateBucket\", \"s3:DeleteObject\", \"s3:GetBucketLocation\", \"s3:GetObject\", \"s3:ListAllMyBuckets\", \"s3:PutObject\"], \"Resource\": \"*\"}]}"
}
```

---

## 4. Mocked Botocore CLI Enforcement Unit Tests (Item 5)

Created `cli/test_enforcement.py` covering:
- `ThrottlingException` retry with exponential backoff on `PutRolePolicy` (succeeds on retry attempt 2).
- `MalformedPolicyDocumentException` handled cleanly (sets status `APPLY_FAILED`, exit code 1).
- `LimitExceededException` handled cleanly (sets status `APPLY_FAILED`, exit code 1).
- `APPLIED_UNVERIFIED` path (read-back mismatch sets `APPLIED_UNVERIFIED` and skips audit recording).

### Test Suite Output (`cli/test_enforcement.py`)
```text
test_1_throttling_retry_success (__main__.TestCliEnforcement.test_1_throttling_retry_success) ... ok
test_2_malformed_policy_document_exception (__main__.TestCliEnforcement.test_2_malformed_policy_document_exception) ... ok
test_3_limit_exceeded_exception (__main__.TestCliEnforcement.test_3_limit_exceeded_exception) ... ok
test_4_applied_unverified (__main__.TestCliEnforcement.test_4_applied_unverified) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.010s

OK
```

---

## 5. Dashboard Deliverable & `dashboard/run.json` (Item 6)

*Label: **Recorded Run Snapshot** (read-only observability view generated from AWS DynamoDB run data, not live websocket polling).*

### Exported Data (`dashboard/run.json`)
```json
{
  "request_id": "51c455ef-08b1-4b4d-8479-e2d49172cb2c",
  "status": "APPLIED",
  "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role",
  "model_used": "apac.amazon.nova-lite-v1:0",
  "completed_at": "2026-09-19T14:14:26.343219+00:00",
  "action_mappings_applied": [
    {
      "original": "s3:HeadObject",
      "mapped": "s3:GetObject"
    },
    {
      "mapped": "s3:ListAllMyBuckets",
      "original": "s3:ListBuckets"
    }
  ],
  "analyzer_validation": {
    "check_no_new_access": {
      "result": "PASS",
      "reasons": [],
      "message": "The modified permissions grant less or equal access compared to your existing policy."
    },
    "messages": [
      "Access Analyzer validation passed (no errors, no new access)."
    ],
    "passed": true,
    "findings": [],
    "reason": null
  },
  "cedar_policy": "permit(\n    principal,\n    action in [\n        CedarSentinel::Action::\"s3:CreateBucket\",\n        CedarSentinel::Action::\"s3:DeleteObject\",\n        CedarSentinel::Action::\"s3:GetBucketLocation\",\n        CedarSentinel::Action::\"s3:GetObject\",\n        CedarSentinel::Action::\"s3:HeadObject\",\n        CedarSentinel::Action::\"s3:ListBuckets\",\n        CedarSentinel::Action::\"s3:PutObject\"\n    ],\n    resource\n);",
  "cedar_validation": {
    "passed": true,
    "messages": [
      "Policy passed STRICT Cedar schema validation."
    ],
    "policy_store_id": "<AVP_STORE_ID>"
  },
  "coverage_check": {
    "passed": true,
    "blocked_actions": "[]"
  },
  "iam_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"CedarSentinelTightenedStmt1\", \"Effect\": \"Allow\", \"Action\": [\"s3:CreateBucket\", \"s3:DeleteObject\", \"s3:GetBucketLocation\", \"s3:GetObject\", \"s3:ListAllMyBuckets\", \"s3:PutObject\"], \"Resource\": \"*\"}]}",
  "observed_actions": {
    "s3:GetObject": "1",
    "s3:HeadObject": "1",
    "s3:CreateBucket": "1",
    "s3:PutObject": "1",
    "s3:GetBucketLocation": "2",
    "s3:ListBuckets": "2",
    "s3:DeleteObject": "1"
  },
  "previous_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"DemoS3Access\", \"Effect\": \"Allow\", \"Action\": \"s3:*\", \"Resource\": \"*\"}]}",
  "rationale": "Tightened policy to include only observed CloudTrail actions for S3, logs, and EC2. Added minimal EC2 actions based on observed 'Describe*' and 'List*' actions.",
  "requested_policy": "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Sid\": \"DemoS3Access\", \"Effect\": \"Allow\", \"Action\": [\"s3:*\"], \"Resource\": \"*\"}, {\"Sid\": \"DemoEC2Access\", \"Effect\": \"Allow\", \"Action\": [\"ec2:Describe*\", \"ec2:List*\"], \"Resource\": \"*\"}, {\"Sid\": \"DemoLogsAccess\", \"Effect\": \"Allow\", \"Action\": [\"logs:CreateLogGroup\", \"logs:CreateLogStream\", \"logs:PutLogEvents\", \"logs:DescribeLogGroups\", \"logs:DescribeLogStreams\", \"logs:GetLogEvents\", \"logs:FilterLogEvents\", \"logs:StartQuery\", \"logs:GetQueryResults\", \"logs:StopQuery\"], \"Resource\": \"*\"}, {\"Sid\": \"DemoDynamoAccess\", \"Effect\": \"Allow\", \"Action\": [\"dynamodb:*\"], \"Resource\": \"*\"}]}",
  "stage_timings": [
    {
      "stage": "cloudwatch_query",
      "start": "2026-09-19T14:14:20.225166+00:00",
      "end": "2026-09-19T14:14:22.459732+00:00"
    },
    {
      "stage": "bedrock_call",
      "start": "2026-09-19T14:14:22.460922+00:00",
      "end": "2026-09-19T14:14:23.554118+00:00"
    },
    {
      "stage": "coverage_check",
      "start": "2026-09-19T14:14:23.555333+00:00",
      "end": "2026-09-19T14:14:23.555787+00:00"
    },
    {
      "stage": "cedar_validation",
      "start": "2026-09-19T14:14:23.555797+00:00",
      "end": "2026-09-19T14:14:23.885670+00:00"
    },
    {
      "stage": "iam_translation",
      "start": "2026-09-19T14:14:23.900226+00:00",
      "end": "2026-09-19T14:14:23.900709+00:00"
    },
    {
      "stage": "analyzer_validation",
      "start": "2026-09-19T14:14:23.900722+00:00",
      "end": "2026-09-19T14:14:26.332309+00:00"
    }
  ],
  "ttl": 1790086466,
  "unmatched_actions": []
}
```

---

## 6. Problems Encountered

1. **Unobserved Action Inclusion in LLM Cedar Drafts:** Bedrock's draft included statements from the requested policy (`ec2:*`, `logs:*`) even when CloudTrail observed only S3 actions. This passed `CheckNoNewAccess` because the tightened policy was still a subset of the requested plan.
   *Resolution:* Implemented deterministic guard in `_sanitize_and_guard_cedar_policy` to drop any actions absent from `observed_actions`.
2. **AVP Description Length Constraint:** Amazon Verified Permissions `CreatePolicy` rejects descriptions exceeding 150 characters with `ValidationException`.
   *Resolution:* Sanitized and truncated description to 140 characters: `f"req={request_id[:8]} rationale={rationale}"[:140]`.
3. **CloudTrail Action Mapping Discrepancies:** Actions like `HeadObject` and `ListBuckets` in CloudTrail authorize against `s3:GetObject` and `s3:ListAllMyBuckets` in IAM.
   *Resolution:* Implemented `CLOUDTRAIL_TO_IAM_ACTION_MAP` in translation stage and confirmed via Access Analyzer `ValidatePolicy`.

---

## 7. Deviations from Plan

1. **Pre-Enforcement Guard Enhancement:** Extended `_sanitize_and_guard_cedar_policy` to enforce observed action filtering before schema validation and IAM translation, guaranteeing unobserved actions can never be applied.
2. **Deterministic Audit Identification:** Added request ID prefixing to persistent AVP policy descriptions to ensure traceability across multiple apply cycles.

---

## 8. Time Spent

- **Stage 5 Translation & Action Normalization:** ~2.5 hours
- **Stage 6 Access Analyzer Integration:** ~2.0 hours
- **CLI Apply & Safety Guards (Section 4 & 5):** ~3.0 hours
- **Persistent AVP Audit Store (Section 6):** ~1.5 hours
- **Dashboard & Sanitized Export Script:** ~1.5 hours
- **Bug Fix, Regression Testing & Extended Redaction:** ~2.0 hours
- **Total Time Spent:** ~12.5 hours
