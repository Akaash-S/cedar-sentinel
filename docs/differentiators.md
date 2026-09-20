<!-- Intended repo path: docs/differentiators.md -->
# Core Differentiators — Cedar Sentinel

This file is the source of truth for how Cedar Sentinel is positioned against existing
tools. Use this wording in the writeup and the demo video narration rather than
re-deriving the pitch from memory — it has already been checked against the actual
architecture in `00-master-blueprint.md` to avoid overclaiming.

---

## 1. Deploy-Time Policy Tightening & Human Approval Workflow

**IAM Access Analyzer:** AWS IAM Access Analyzer already generates policies from CloudTrail activity and recommends removing unused permissions.

**Cedar Sentinel:** Builds on Access Analyzer rather than replacing it. It incorporates Access Analyzer's `ValidatePolicy` and `CheckNoNewAccess` APIs directly into its evaluation pipeline. What Cedar Sentinel adds is a developer-focused, deploy-time workflow:
1. Intercepts the proposed IAM policy from a Terraform plan (`terraform show -json`).
2. Correlates it with observed CloudTrail usage across the role's historical execution window.
3. Generates a readable, schema-valid Cedar policy via Amazon Bedrock and Amazon Verified Permissions (AVP).
4. Translates back to minimal IAM JSON, verifies no privilege escalation via Access Analyzer, and presents an interactive before/after diff for explicit developer sign-off (`[y/N]`).
5. Snapshots the prior policy, enforces the update to the live IAM role, and logs the approved Cedar policy to a persistent AVP audit store.

---

## 2. Dual-Layer Verification (Cedar STRICT Schema + IAM Access Analyzer)

- **Cedar Schema Verification:** Synthesizes Cedar authorization policies and validates them in `STRICT` mode against Amazon Verified Permissions before translation.
- **IAM Access Analyzer Safety Net:** Independent mathematical validation using AWS Automated Reasoning tools:
  - `ValidatePolicy`: Flags invalid action syntax or malformed elements.
  - `CheckNoNewAccess`: Guarantees the tightened policy never grants permissions outside the original requested baseline.

---

## 3. Workload Lockout Safeguards & Observed Action Guard

Automated least-privilege generation risks dropping actions that are necessary for workload operation. Cedar Sentinel mitigates this with:
1. **Deterministic Guard:** Asserts that every action observed in CloudTrail telemetry is preserved in the tightened policy.
2. **Human Approval Step:** Gives the developer full visibility into the diff before any live IAM changes occur.
3. **Rollback Snapshot:** Automatically saves the previous policy state to DynamoDB before applying changes.

---

## Summary Table

| Capability | IAM Access Analyzer Alone | Cedar Sentinel Pipeline |
|---|---|---|
| Trigger | Console / scheduled finding | Deploy-time workflow (`terraform show -json`) |
| Policy Validation | `ValidatePolicy` / `CheckNoNewAccess` | Cedar STRICT schema validation + Access Analyzer |
| Workload Safety | Recommendations | Deterministic observed-action guard + diff approval |
| Rollback & Audit | Manual copy-paste | Automated DynamoDB snapshot + AVP audit store |

---

## Confirmed decisions log

| Question | Decision |
|---|---|
| First-deploy demo pacing | Start mid-stream from a pre-seeded, already-running role (`cedar-sentinel-demo-role`). |
| Continuous loop: build vs. narration | CLI triggered on demand; narration credits EventBridge/SQS architecture as designed for background evaluation. |
| Lockout-check failure handling | Hard-block with non-zero exit + explicit developer choice (`[1] fallback / [2] override [disabled] / [3] re-evaluate`). |
| Safe apply & Rollback | CLI checks target inline policy exists before applying, snapshots `previous_policy` to DynamoDB, executes `PutRolePolicy` with retry/backoff, confirms via read-back, and writes audit record to persistent AVP store. |
