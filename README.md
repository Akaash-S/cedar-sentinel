# Cedar Sentinel

> Automated Least-Privilege IAM Policy Synthesis, Cedar Verification & Safe IAM Enforcement via Amazon Bedrock & Amazon Verified Permissions.

**Track:** Ship It  
**Status:** Phase 3 — IAM Translation & Enforcement Complete  
**Live Dashboard (Amplify):** https://main.d3i4xcsmv7sca9.amplifyapp.com  

---

## Overview

**Cedar Sentinel** is an automated IAM governance and least-privilege enforcement pipeline designed for modern AWS cloud infrastructure. Instead of relying on manual policy reviews or static linting that lacks runtime context, Cedar Sentinel intercepts planned IAM policies from Terraform changes, correlates them with historical CloudTrail usage via CloudWatch Logs Insights, synthesizes verified Cedar policies with Amazon Bedrock and Amazon Verified Permissions (AVP), translates them to tightened IAM JSON with automated action normalization, validates them via IAM Access Analyzer (`ValidatePolicy` and `CheckNoNewAccess`), and safely enforces them to live IAM roles with human-in-the-loop approval.

---

## Pipeline Architecture

```
Terraform Plan JSON
        │
        ▼
   Python CLI ────────► EventBridge ─────► SQS ─────► Lambda Pipeline Processor
   (--apply)                                            │
                                                        ├─ 1. CloudWatch Logs Insights (7-day usage query)
                                                        ├─ 2. Amazon Bedrock (Nova Lite / Llama 70B reasoning)
                                                        ├─ 3. Coverage Check (prevents workload lockout)
                                                        ├─ 4. Cedar Formal Verification (AVP STRICT schema)
                                                        ├─ 5. IAM Translation & Action Normalization
                                                        └─ 6. IAM Access Analyzer (ValidatePolicy + CheckNoNewAccess)
                                                        │
                                                        ▼
                                                  DynamoDB Table
                                                        │
   CLI Interactive Diff & Approval ◄────────────────────┘
        │
        ├─ [N] Decline ──► Writes DECLINED status (no IAM changes)
        │
        └─ [y] Approve ──► Snapshot previous_policy
                       ──► iam:PutRolePolicy (with backoff)
                       ──► Eventual-consistency read-back verification
                       ──► Record audit policy in persistent AVP store
                       └── Status: APPLIED
```

---

## CLI Usage

### 1. Read-Only Policy Analysis (Dry-Run)
Analyzes the Terraform plan, queries CloudTrail history, synthesizes a tightened Cedar policy, and validates it without making any live IAM modifications:

```bash
python cli/cedar_sentinel.py analyze \
  --plan-file cli/fixtures/demo-role-plan.json \
  --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role \
  --publish
```

### 2. Full Enforcement Flow (`--apply`)
Executes the full pipeline, displays a formatted before/after diff with applied action mappings and non-blocking Access Analyzer findings, prompts the developer for confirmation (`[y/N]`), snapshots the existing policy, applies the tightened policy, verifies read-back consistency, and logs the approved Cedar policy to the persistent AVP audit store:

```bash
python cli/cedar_sentinel.py analyze \
  --plan-file cli/fixtures/demo-role-plan.json \
  --role-arn arn:aws:iam::<ACCOUNT_ID>:role/cedar-sentinel-demo-role \
  --apply \
  --policy-name demo-broad-s3
```

### 3. Built-in Safety Guards on `--apply`
- **Lambda Role Protection:** Strictly refuses to modify Cedar Sentinel's own execution role (even if `--allow-self-analysis` is supplied).
- **Role Name Restriction:** `--apply` is restricted to roles matching `cedar-sentinel-*`.
- **Target Policy Verification:** Calls `iam:ListRolePolicies` to ensure `--policy-name` is an existing inline policy; refuses to silently create parallel policies.
- **Access Analyzer Safety Net:** Automatically blocks apply on syntax errors (`VALIDATION_ERROR`) or privilege escalation (`NEW_ACCESS`).
- **Workload Lockout Prevention:** Hard-blocks on dropped observed actions (`BLOCKED` status). Option `[2]` force-apply override is intentionally disabled with an explicit safety notice.

---

## Local Dashboard (Live Mode)

Cedar Sentinel provides a local, read-only developer dashboard server that visualizes live pipeline runs directly from your AWS account or offline fixtures.

```bash
# Start local live dashboard (queries DynamoDB using local AWS credentials)
python cli/cedar_sentinel.py dashboard

# Start dashboard focused on a specific run ID without auto-opening the browser
python cli/cedar_sentinel.py dashboard --run-id <REQUEST_ID> --no-open

# Run offline against recorded run fixtures (zero AWS calls)
python cli/cedar_sentinel.py dashboard --offline-dir dashboard/runs

# Disable account ID and ARN masking (for internal developer debugging)
python cli/cedar_sentinel.py dashboard --show-real-ids
```

### Safety & Architecture
- **Read-Only & Loopback Only:** Binds exclusively to `127.0.0.1`. Rejects all write methods (HTTP 405) and enforces strict `Host` and `Origin` header validation against DNS rebinding.
- **Default Redaction:** Automatically masks AWS account numbers (`<ACCOUNT_ID>`), AVP policy store IDs (`<AVP_STORE_ID>`), and CloudWatch log groups unless `--show-real-ids` is explicitly passed.
- **Minimal IAM Permissions:** The developer's local AWS identity requires only:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "CedarSentinelDashboardReadOnly",
        "Effect": "Allow",
        "Action": [
          "dynamodb:Scan",
          "dynamodb:GetItem",
          "dynamodb:DescribeTable",
          "sts:GetCallerIdentity"
        ],
        "Resource": "arn:aws:dynamodb:*:*:table/cedar-sentinel-results"
      }
    ]
  }
  ```

---

## Repeatable Demos & Demo Reset Script

To reset the demo role back to its broad baseline (`s3:*`) for repeatable demonstrations:

```bash
python scripts/reset_demo_role.py --role-name cedar-sentinel-demo-role --policy-name demo-broad-s3
```
*Note: `reset_demo_role.py` is hard-coded to refuse any role other than `cedar-sentinel-demo-role`.*

---

## Manual Rollback Procedure

Cedar Sentinel snapshots the existing inline policy before executing `PutRolePolicy` and records it as `previous_policy` in the DynamoDB `cedar-sentinel-results` table item.

To manually roll back an applied policy:
1. Retrieve the `previous_policy` document from the DynamoDB results item:
   ```bash
   aws dynamodb get-item \
     --table-name cedar-sentinel-results \
     --key '{"request_id": {"S": "<REQUEST_ID>"}}' \
     --projection-expression "previous_policy"
   ```
2. Restore the previous policy back to the target role:
   ```bash
   aws iam put-role-policy \
     --role-name cedar-sentinel-demo-role \
     --policy-name demo-broad-s3 \
     --policy-document file://previous_policy.json
   ```

---

## Exporting Run Snapshot to Dashboard

To export a completed run to the static Amplify dashboard:

```bash
# Export a real completed run
python scripts/export_run.py --request-id <REQUEST_ID> --out dashboard/runs/<name>.json --label "<LABEL>"

# Validate all recorded runs and manifest
python scripts/validate_runs.py
```
This sanitizes 12-digit AWS account IDs, AVP store IDs, and log groups, updates `dashboard/runs/index.json`, and prepares recorded runs for static dashboard replay.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
