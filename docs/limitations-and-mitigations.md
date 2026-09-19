<!-- Intended repo path: docs/limitations-and-mitigations.md -->
# Limitations & Mitigations Log — Cedar Sentinel

This file tracks every known limitation of the system honestly, split into what's
fixable **within the event window** and what's real **future work**. Judges score
"Learning" partly on whether a team understands the edges of what they built — this
doc is the source of truth for that section of the writeup. Do not soften or omit an
entry to make the project look more finished than it is.

---

## How to use this file

- Add an entry the moment a limitation is discovered, not retroactively on Day 4.
- Every entry gets a **status**: `Mitigated in event window`, `Partially mitigated`,
  or `Future work — not attempted`.
- The "Future work" entries are not failures — naming them clearly is itself part of
  the submission's Learning section. Do not attempt to build these during the event.

---

## Part A — Fixable within the 4-day window

| # | Limitation | Mitigation applied | Status |
|---|---|---|---|
| 1 | Scope too large for a solo 4-day build (8 moving parts: Go proxy, EventBridge, SQS, Lambda, CloudTrail Lake, Bedrock, Cedar/AVP, IAM translation, dashboard) | Protect the core loop only: CloudTrail → Bedrock → Cedar → IAM translation. Switched to Python CLI reading Terraform plan JSON. Dashboard implemented as a clean recorded-run replay from DynamoDB data. Features frozen at end of Phase 3. | `Mitigated in event window` |
| 2 | CloudTrail usage history baseline data | Deliberately seeded real usage activity on `cedar-sentinel-demo-role` (S3 bucket creation, object put/get/delete, log group interactions) to provide an authentic over-permission baseline to tighten. Disclosed openly in writeup. | `Mitigated in event window` |
| 3 | Bedrock may drop observed actions or draft unsound policies | Multi-layered safety net: (1) Stage 3 coverage check hard-blocks if any observed action is dropped; (2) Stage 4 formal verification compiles against Amazon Verified Permissions STRICT Cedar schema; (3) Stage 6 IAM Access Analyzer validates syntax and ensures `CheckNoNewAccess`. | `Mitigated in event window` |
| 4 | Single point of failure — solo build, no teammate code review | Extensive automated unit test suites (`test_translator.py`, `test_access_analyzer.py`, `test_cedar_rejection.py`) and step-by-step CLI guard testing. Tagged commits for clean rollback checkpoints. | `Mitigated in event window` |
| 5 | Demonstrating end-to-end async pipeline clearly in video | Scripted one linear scenario: `cedar-sentinel-demo-role` with broad `s3:*` policy, analyzed via CLI, reviewed with full before/after diff and verified against Cedar & Access Analyzer, and applied with read-back verification. | `Mitigated in event window` |
| 6 | Cedar STRICT schema validation cannot detect privilege escalation | Because the disposable AVP schema is synthesized dynamically from the draft policy's actions, Cedar validation validates schema/syntax consistency but cannot detect if permissions escalated beyond the baseline. **Mitigation:** Stage 6 independently executes `accessanalyzer:CheckNoNewAccess` comparing the translated policy against the requested baseline policy. Rejects with `ANALYZER_INVALID` if new access is granted. | `Mitigated in event window` |
| 7 | CloudTrail `eventName` does not always equal IAM action name | CloudTrail API event names often diverge from IAM action names (e.g. `s3:ListBuckets` $\rightarrow$ `s3:ListAllMyBuckets`, `s3:HeadObject` $\rightarrow$ `s3:GetObject`, `s3:HeadBucket` $\rightarrow$ `s3:ListBucket`). **Mitigation:** Implemented deterministic `CLOUDTRAIL_TO_IAM_ACTION_MAP` in translation stage; IAM Access Analyzer `ValidatePolicy` acts as an automated catch-all for any unmapped invalid action names. | `Partially mitigated` |
| 8 | CloudTrail records management events by default (data events require explicit opt-in) | Without S3 data events enabled on the trail, object-level actions (`GetObject`, `PutObject`, `DeleteObject`) are omitted from CloudWatch Logs history. A policy tightened strictly from management events would drop object-level access. **Mitigation:** S3 data events were enabled for the demo bucket during pre-flight and re-seeded. For general workloads, documented as a prerequisite for S3 object-level least-privilege analysis. | `Partially mitigated` |
| 9 | `iam:PutRolePolicy` failure modes and eventual consistency | Handled with exponential backoff retry for `ThrottlingException`, distinct error reporting for `MalformedPolicyDocumentException` and `LimitExceededException` without raw stack traces, and eventual-consistency read-back verification with `APPLIED_UNVERIFIED` state if unconfirmed. Existing policy is snapshotted to `previous_policy` in DynamoDB prior to overwrite; other existing policies on the role are detected and reported. Automated rollback is omitted (manual rollback documented in README). | `Mitigated in event window` |
| 10 | Lockout-menu option `[2]` (force-apply draft policy) disabled | Option `[2]` in the CLI menu is intentionally disabled in this build with an explicit safety notice: force-applying a policy that dropped observed actions would directly bypass the workload-lockout safeguard. Developers are directed to use `[3]` to re-evaluate with hint context or `[1]` to fall back to the original policy. | `Mitigated in event window` |
| 11 | `accessanalyzer:CheckNoNewAccess` bounds policy against requested plan, not observed usage | `CheckNoNewAccess` compares the new translated policy against the requested plan policy. If a requested plan contains `s3:*` and `ec2:*`, `CheckNoNewAccess` mathematically verifies that the new policy does not grant permissions outside `s3:*` and `ec2:*`. It does **not** check whether permissions are bounded by actual CloudTrail observed calls. **Mitigation:** Layered safety model: the deterministic observed-action guard strictly bounds the draft to observed calls, while `CheckNoNewAccess` guarantees zero privilege escalation beyond the developer's requested plan. | `Mitigated in event window` |
| 12 | Deterministic observed-action guard (`guard_removed_actions`) | Generative models (Bedrock Nova Lite) can occasionally retain or synthesize unobserved actions permitted by the requested plan. **Mitigation:** Implemented a post-generation deterministic AST sanitizer (`_sanitize_and_guard_cedar_policy`) in Lambda that extracts all action names from the Cedar draft and strips any action not present in the CloudTrail observed action map (accounting for bidirectional CloudTrail $\leftrightarrow$ IAM mapping). Stripped actions are logged in `guard_removed_actions` in DynamoDB and the rationale is adjusted. | `Mitigated in event window` |
| 13 | `accessanalyzer:ValidatePolicy` does not flag `Resource: "*"` with wildcards | `ValidatePolicy` performs syntactic and structural linting (schema, valid actions, syntax errors). It does not treat `Resource: "*"` on read/write actions as a security error, because `Resource: "*"` is structurally valid IAM syntax. **Mitigation:** Highlighted in limitations; developer dry-run diff review provides the human verification layer for resource scoping. | `Mitigated in event window` |
| 14 | No resource-level tightening (Resource remains `*`) | The current Cedar translator scopes actions to observed APIs but retains the requested resource scope (`Resource: "*"` or specific ARNs provided in the plan) rather than dynamically synthesizing resource ARNs down to bucket/prefix level. **Mitigation:** Action-level least-privilege is strictly enforced; dynamic resource-level ARN synthesis from CloudTrail requestParameters is scoped as future work. | `Partially mitigated` |

---

## Part B — Future work (explicitly out of scope for the event)

| # | Limitation | Why it can't be solved in the event window | Direction for future work |
|---|---|---|---|
| 15 | Comprehensive CloudTrail-to-IAM action resolver | Thousands of AWS APIs across hundreds of services have non-1:1 mappings. Building a full universal resolver requires scraping or bundling AWS IAM service authorization reference tables. | Integrate automated IAM service reference database (e.g. `iam-dataset` or AWS IAM Authorization Reference scraper) to dynamically resolve arbitrary CloudTrail events to IAM actions. |
| 16 | Query cost and volume at enterprise scale | Enterprise CloudTrail streams produce gigabytes of daily events across hundreds of AWS accounts. | Incrementally maintain pre-aggregated role-to-action graph representations using AWS Athena or event streams, querying only delta windows. |
| 17 | Human approval bottleneck at enterprise scale | Manual dry-run review cannot scale to thousands of daily IAM policy updates. | Policy risk-tiering: auto-apply non-breaking low-risk tightenings (e.g. removing actions with 0 calls in 90 days), routing only sensitive tier-1 actions (IAM, KMS, Security) to human approval queues. |
| 18 | Automated one-click rollback mechanism | Out of scope for a 4-day build. | Add a dedicated `cedar-sentinel rollback --request-id <id>` command that retrieves `previous_policy` from DynamoDB and applies it via `iam:PutRolePolicy`. |

---

## Section for the final writeup

> "Cedar Sentinel's dry-run-and-approve design is intentional, not a stopgap: Bedrock's
> policy suggestions are treated as a draft, not a decision. Cedar/Verified Permissions
> checks internal logical soundness before a human ever sees the diff, IAM Access Analyzer
> independently ensures no privilege escalation, and functional correctness for the specific
> workload still depends on the developer's approval step.
> At event scale, we validated this loop against a single role with a controlled usage
> pattern. Scaling this to a real organization — cost-bounded CloudTrail queries, batched
> Bedrock reasoning, risk-tiered auto-approval, universal IAM mapping, and multi-account aggregation — is the
> clearly scoped next phase, not something this build claims to have solved."

---

*Cross-reference: `docs/architecture.md` for the deviation log, `instructions/00-master-blueprint.md`
Section 7 for judging alignment, and `docs/ai-tool-disclosure.md` for what AI tooling was
used to reason through these mitigations.*
