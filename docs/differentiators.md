<!-- Intended repo path: docs/differentiators.md -->
# Core Differentiators — Cedar Sentinel

This file is the source of truth for how Cedar Sentinel is positioned against existing
tools. Use this wording in the writeup and the demo video narration rather than
re-deriving the pitch from memory — it has already been checked against the actual
architecture in `00-master-blueprint.md` to avoid overclaiming.

---

## 1. Continuous Tightening vs. One-Time Post-Hoc Auditing

**The competition:** Tools like IAM Access Analyzer, Repokid, and Wiz generate a
least-privilege snapshot when you run them, but nothing re-checks the role after that.
Permissions drift back toward over-broad the next time someone edits the Terraform,
and re-auditing depends on a human remembering to re-run the tool.

**Cedar Sentinel:** Evaluates Terraform plans against fresh CloudTrail telemetry from
the workload's operational history. It closes the loop across deploy cycles,
catching permission drift automatically rather than requiring a scheduled or manual audit.

**Demo strategy:** The video starts mid-stream from a pre-provisioned role
(`cedar-sentinel-demo-role`) that already has a broad policy (`s3:*`) with real
seeded CloudTrail usage history already in place. The CLI trigger (`python cli/cedar_sentinel.py analyze --plan-file ... --role-arn ... --apply --policy-name demo-broad-s3`)
reads the seeded history and produces the "Before (Wildcard) vs. After (Cedar & IAM Least-Privilege)" diff on screen immediately.

---

## 2. Native Cedar Policy Generation vs. Legacy IAM JSON

**The competition:** Almost all existing solutions default strictly to traditional AWS
IAM JSON documents, which become dense and difficult to audit as policies accumulate
conditions and exceptions at scale.

**Cedar Sentinel:** Synthesizes Cedar authorization policies natively for Amazon Verified
Permissions before translating down to IAM JSON. Cedar's policy language is
human-readable and formally analyzable — schema-validated in STRICT mode against AVP — which
is the modern standard for fine-grained authorization.

---

## 3. Closed-Loop Safeguard Against Workload Lockouts & Privilege Escalations

**The competition:** Automated least-privilege generators risk stripping away
operations that simply haven't appeared in recent telemetry — silently breaking application
workloads on the next deploy — or introducing privilege escalation errors.

**Cedar Sentinel:** Combines Bedrock's generative drafting with a multi-layered verification safety net:
1. **100% Coverage Check:** Asserts that every action observed in the CloudTrail baseline remains permitted.
2. **Cedar Formal Verification:** Amazon Verified Permissions validates the policy against a STRICT Cedar schema.
3. **IAM Access Analyzer Independent Verification:** Calls `ValidatePolicy` (catching invalid IAM action syntax) and `CheckNoNewAccess` (catching any potential privilege escalation).
4. **Human-in-the-Loop Dry-Run Approval:** Presents a complete before/after diff with applied action mappings and requires explicit developer sign-off (`[y/N]`) before applying anything to IAM.

**Failure behavior:**
- If the coverage check fails, the CLI hard-blocks the deployment with a three-way menu (`[1] Fall back to original policy`, `[2] Force-apply draft policy (Override)`, `[3] Re-evaluate with tighter prompt context`).
- *Note on Option [2] Override:* Option `[2]` is intentionally disabled in this build with an explicit safety warning (`Override is intentionally disabled in this build: applying a policy that drops observed actions bypasses the lockout safeguard. Use [3] to re-evaluate or [1] to fall back.`).

---

## Summary table (for the writeup)

| Differentiator | Competitor approach | Cedar Sentinel approach |
|---|---|---|
| Timing | One-time, on-demand snapshot | Continuous, per-deploy-cycle evaluation |
| Policy format | AWS IAM JSON | Cedar (Verified Permissions), then translated to IAM |
| Lockout & Escalation risk | Usage-window blind spots can silently break workloads or escalate access | Deterministic 100%-coverage check + Cedar verification + Access Analyzer `CheckNoNewAccess` + human dry-run approval |

---

## Confirmed decisions log

| Question | Decision |
|---|---|
| First-deploy demo pacing | Start mid-stream from a pre-seeded, already-running role (`cedar-sentinel-demo-role`). |
| Continuous loop: build vs. narration | CLI triggered on demand; narration credits EventBridge/SQS architecture as designed for background evaluation. |
| Lockout-check failure handling | Hard-block with non-zero exit + explicit developer choice (`[1] fallback / [2] override [disabled] / [3] re-evaluate`). |
| Safe apply & Rollback | CLI checks target inline policy exists before applying, snapshots `previous_policy` to DynamoDB, executes `PutRolePolicy` with retry/backoff, confirms via read-back, and writes audit record to persistent AVP store. |
