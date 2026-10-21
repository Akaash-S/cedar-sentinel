# Project Master Blueprint
## Autonomous AWS IAM Least-Privilege Enforcer — "Cedar Sentinel"

**Event:** First Commit — Bharat Builds Tour (WeMakeDevs × AWS)
**Track:** Ship It (solo)
**Builder graduation year:** 2027 (Final Year — Amazon fast-track eligible)
**Document status:** Living blueprint — v1.3, re-verified against live event pages Sep 12, 2026; interception CLI updated to Python Sep 14, 2026; historical baseline updated to CloudWatch Logs Sep 17, 2026

**Revision note (Sep 14, 2026):** Earlier versions of this document specified a Go CLI
proxy intercepting `terraform apply` live, with a Day-2 checkpoint to fall back to a
Python CLI reading Terraform plan JSON if Go wasn't working reliably. That fallback path
is adopted from Day 1 instead — the task never required live interception, only reading
a file Terraform already produces. See `docs/architecture.md`'s deviation log for the
full reasoning.

**Revision note (Sep 17, 2026 — kickoff day):** AWS closed CloudTrail Lake to new
customers on May 31, 2026 (existing customers unaffected). This account is a new
CloudTrail Lake customer, so attempting to create an event data store returns
`InvalidParameterException: CloudTrail Lake is no longer accepting new customers`.
Every reference to CloudTrail Lake as the historical-usage baseline is replaced with a
standard **CloudTrail Trail delivering to CloudWatch Logs**, queried via **CloudWatch
Logs Insights** — a capability AWS explicitly points new customers toward as the
replacement, unaffected by the closure since it's a separate CloudTrail feature. Pricing
is equivalent ($0.005/GB scanned for queries, same as Lake), and nothing downstream of
"Lambda has a usage baseline it can query" changes. See `docs/architecture.md`'s
deviation log for the full reasoning.

---

## 1. Executive Summary & Problem Statement

Modern cloud environments suffer from pervasive over-permissioning. Developers routinely grant wildcard access (`*:*` or overly broad `Resource: "*"`) to move fast during prototyping, and that blast radius rarely gets tightened later. Manual IAM audits are slow, infrequent, and don't scale with the rate at which new roles and policies get created.

**Cedar Sentinel** is a developer-facing tool that:

1. Watches AWS API calls a workload actually makes during real usage (via CloudTrail).
2. Uses Amazon Bedrock to reason about the delta between a *requested* IAM policy (e.g. attached in a Terraform plan) and the *actually used* permissions.
3. Synthesizes a tightened, least-privilege policy recommendation.
4. Uses Cedar's formal, analyzable policy model to **verify** the recommendation is logically sound (no accidental privilege escalation, no contradictory statements) before it's ever applied.
5. Requires explicit developer approval (dry-run) before anything is enforced.

This targets Cloud/DevOps/Security engineers — the same persona Amazon's fast-track pipeline scouts for.

---

## 2. ⚠️ Critical Technical Correction

Amazon Verified Permissions (AVP) is built to be the externalized permission engine for **your own applications**, not a gate on real AWS API calls. AWS IAM is what actually controls what a role can do against AWS resources.

**Corrected architecture:**
- **Cedar/AVP's job:** a formally analyzable verification layer — check the AI-synthesized permission set for logical soundness before it's translated into anything real.
- **What actually enforces least privilege:** a generated IAM policy document, applied via `iam:PutRolePolicy` / a patched Terraform file, with explicit developer approval.

This is a *stronger* story for judges: it shows you understand the boundary between application-layer authorization (Cedar/AVP) and AWS-layer enforcement (IAM).

---

## 3. Target Persona & Hackathon Alignment

Built for Cloud & DevOps/Security engineers — deliberately not a generic AI wrapper. Maps directly to the "Built on AWS" judging criterion and to the 2027-eligible Amazon fast-track track.

---

## 4. High-Level Architecture (corrected)

```
[Developer: terraform apply / plan]
        │
        ▼
[Python CLI] ── reads `terraform show -json`, extracts the IaC-requested
        │        IAM policy, tags the run
        ▼
[Amazon EventBridge] ──(SQS buffer)──► [AWS Lambda, Python 3.12]
        │                                      │
        │                                      ▼
        │                     [CloudTrail Trail → CloudWatch Logs — narrow,
        │                      scoped Logs Insights query: actual API calls
        │                      made by this role]
        │                                      │
        │                                      ▼
        │                     [Amazon Bedrock — diff requested vs. actual,
        │                      draft a tightened permission set]
        │                                      │
        │                                      ▼
        │                     [Cedar: express + validate via Verified
        │                      Permissions — schema check, contradiction/
        │                      escalation analysis]
        │                                      │
        │                                      ▼
        │                     [Translate verified Cedar → IAM policy JSON]
        ◄──────────────────────────────────────┘
        │  (recommended IAM policy returned to CLI)
        ▼
[Dry-run diff shown to developer, explicit approval required]
        ▼
[Approved: iam:PutRolePolicy or patched Terraform file]
        ▼
[Verified Permissions stores the Cedar-expressed policy as an auditable record]
```

The CLI does not intercept `terraform apply` in flight. The developer runs
`terraform plan -out=tfplan.binary && terraform show -json tfplan.binary > tfplan.json`,
then `python cedar_sentinel.py analyze --plan-file tfplan.json` — a two-command habit,
not a background process.

---

## 5. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Interception CLI | Python | Reads `terraform show -json` output directly; no live interception needed for what this task requires |
| Async orchestration | EventBridge + SQS | Decouples reasoning latency from the deploy path |
| Compute | Lambda, Python 3.12 | |
| Historical baseline | CloudTrail Trail + CloudWatch Logs Insights | CloudTrail Lake is closed to new customers as of May 31, 2026 — a standard Trail delivering management events to CloudWatch Logs, queried via Logs Insights, is the equivalent path; keep queries narrow (cost) |
| Reasoning | Amazon Bedrock | Verify current model ID in console on Day 1 — don't hardcode in advance |
| Policy verification | Cedar via Verified Permissions API | Called via AWS SDK's `verifiedpermissions` package (boto3) |
| Enforcement | AWS IAM | The real enforcement layer — see Section 2 |
| Dashboard | AWS Amplify Hosting | Dry-run diff viewer; also your Ship It submission URL |
| Auth (optional) | Cognito | Only if time allows |

---

## 6. Step-by-Step Execution Journey

1. Interception: CLI reads the requested IAM policy from a Terraform plan's JSON output.
2. Async buffering via EventBridge → SQS.
3. Contextual analysis: Lambda runs a scoped CloudWatch Logs Insights query against the CloudTrail-delivered log group.
4. AI synthesis: Bedrock drafts a tightened permission set + rationale.
5. Formal verification: expressed as Cedar, validated via Verified Permissions.
6. Translation: verified Cedar → IAM policy JSON.
7. Dry-run + explicit approval.
8. Enforcement: `PutRolePolicy` / Terraform patch.
9. Audit trail: Cedar policy + rationale stored in Verified Permissions.

---

## 7. Risk Mitigation & Checkpoints

| Risk | Mitigation |
|---|---|
| AI hallucination | Mandatory dry-run + Cedar logical-soundness check before any IAM change |
| Context window overflow | Lambda pre-processes raw log data into a compact action-resource graph |
| CloudWatch Logs Insights cost | Scope queries to specific event types and short time windows; hackathon-scale usage should stay within the 5 GB/month free tier for both ingestion and queries |
| Bedrock model ID drift | Check console "Model access" on Day 1, don't hardcode in advance |
| Running out of time | Freeze features end of Day 3; Day 4 is video + writeup + submission only |
| AWS service availability changes mid-build | Re-verify each service's current status against the console before relying on a prior doc's assumption — this is exactly what caught the CloudTrail Lake closure |

---

## 8. Git Branching, Tagging & Deployment Strategy

**Repo structure:**
```
/cli   /lambda   /infra   /dashboard   /docs   README.md
```

**Branches:** `main` (protected) ← `phase-1-setup` ← `phase-2-core-logic` ← `phase-3-enforcement` ← `phase-4-demo-polish`, each merged via PR (squash), commit messages naming the AWS services touched.

**Tags:** `v0.1-setup` (Day 1) → `v0.2-core-reasoning` (Day 2) → `v0.3-enforcement` (Day 3) → `v1.0-submission` (final).

**Deployment:** backend via AWS SAM (`/infra`); dashboard via Amplify Hosting auto-deploy from `main` (this is your Ship It URL); the CLI lives at `/cli` as a plain Python script/package, no build artifact to publish.

---

## 9. Hackathon Timeline

| Day | Date | Branch | Goal |
|---|---|---|---|
| Thu (kickoff) | Sep 17 | `phase-1-setup` | Repo live, services provisioned, CloudWatch Logs Insights query scoped, Python CLI reading Terraform plan JSON working |
| Fri (build) | Sep 18 | `phase-2-core-logic` | Lambda + Bedrock + Cedar verification built |
| Sat (Bangalore optional / online continues) | Sep 19 | `phase-3-enforcement` | IAM translation + application, dashboard live, full pipeline rehearsed |
| Sun (submission) | Sep 20 | `phase-4-demo-polish` → `v1.0-submission` | Record video, write submission, adapt into an **AWS Builder Center post**, submit early |

---

## 10. Judging Alignment Recap

- **Idea & impact:** real, narrow, demonstrable pain point.
- **Built on AWS:** Bedrock, CloudWatch Logs, IAM, Verified Permissions/Cedar are all structurally necessary.
- **Learning:** the Section 2 correction, the Go→Python scope cut, and the CloudTrail Lake closure pivot are all genuine, tellable learning material — the last one especially, since it was an unforeseeable service-availability change hit on kickoff day itself.
- **Execution:** a narrower, five-part core loop (CLI → Lambda → Bedrock → Cedar → IAM) designed to be fully working, rather than an ambitious pipeline that's partially working.
- **Demo video:** an over-permissive policy caught, explained, and safely tightened — visually simple, legible in 3 minutes.

---

## 11. AWS Builder Center Blog Post — "Top Blogs" Prize

Publish the writeup (problem, stack, what fought back) on **AWS Builder Center** specifically, link it in the submission. Top 5 authors get a Logitech keyboard. Low-effort since it reuses writeup content — scheduled as a Day 4 action item.

---

## 12. Rules Compliance Checklist (re-verified against live pages, Sep 12, 2026)

| Rule | Status |
|---|---|
| University student, 18+, individually registered | Confirmed (2027 Final Year) |
| WeMakeDevs account + verified AWS Builder Center profile | Action item — before Sep 17 |
| Solo, ≤4 people | Confirmed: solo |
| No project work before the clock starts | Planning docs are fine now; no code before Sep 17 |
| Prior work doesn't qualify | Fresh repo on Sep 17 |
| AWS usage visible in the video, not just the writeup | Bedrock, CloudWatch Logs, IAM all shown on screen |
| AI tools named in the writeup | Tracked continuously in `docs/ai-tool-disclosure.md` |
| External code/assets credited + licensed | Tracked in `docs/attribution.md` |
| One repo, one video, one writeup, one submission, before deadline | Structure in place |
| Late submissions never scored | Freeze features end of Day 3 |
| Repo history must match the event window | Branching/tagging strategy makes this naturally true |
| Fast-track eligibility depends on accurate/verified registration | Double-check Builder Center verification before Sep 17 |
| Exact kickoff time, mentor sessions, final deadline | **Still unpublished as of Sep 12** — re-check the schedule page yourself close to the event |

---

## 13. Open Items to Verify Before/During Build

- [ ] Confirm current Bedrock model access in your account's region (Day 1, first task) — note Anthropic models require a one-time usage form even though most models are now enabled by default
- [x] ~~Confirm CloudTrail Lake event data store is active and query-able~~ — superseded; confirm CloudTrail Trail is logging and its CloudWatch Logs group is receiving events instead
- [ ] Decide the exact IAM permission scope your own Lambda execution role needs
- [ ] Confirm exact submission deadline and form link once published

---

*Next artifacts live in `/instructions` (agent-facing build instructions per phase) and `/responses` (the agent's completion report per phase).*
