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
| 1 | Scope too large for a solo 4-day build (8 moving parts: Go proxy, EventBridge, SQS, Lambda, CloudTrail Lake, Bedrock, Cedar/AVP, IAM translation, dashboard) | Protect the core loop only: CloudTrail → Bedrock → Cedar → IAM translation. Go proxy, Cognito, dashboard polish are cut-first items. Day-2 checkpoint (Go proxy → Python CLI reading a Terraform plan JSON) triggers on schedule, not when it "feels" broken. Freeze features end of Day 3. | *(fill in during build)* |
| 2 | CloudTrail Lake may not accumulate a rich enough real usage history over a hackathon weekend | Deliberately seed a controlled usage pattern on Day 1: create a test role, call a narrow, specific set of AWS APIs against a role granted much broader access, so Bedrock has a clean over-permission signal to diff against. Disclose this openly in the writeup as a controlled demo dataset, not organic traffic. | *(fill in during build)* |
| 3 | Bedrock may draft an incorrect or overly narrow policy that is "logically sound" (per Cedar) but functionally wrong for the workload | Do not try to eliminate this risk — demonstrate the safeguard instead. Add a pre-check before Cedar verification: does the proposed policy still cover every action actually observed in the CloudTrail sample? Flag any dropped-but-used action automatically. Show the dry-run catching an imperfect first draft in the demo video. | *(fill in during build)* |
| 4 | Single point of failure — solo build, no teammate code review | Commit and tag frequently per the existing `v0.1` → `v1.0` scheme so there is always a working checkpoint to revert to. Keep the dashboard minimal (Phase 1 placeholder approach) so it never blocks the Ship It URL from existing. | *(fill in during build)* |
| 5 | An 8-component async pipeline is hard to demo convincingly in a 3-minute video | Script one linear scenario: one role, one over-permissive policy, one before/after. Show input (Terraform-granted policy) → output (tightened policy + Cedar verification pass) → approval click. Infrastructure hops are implied, not narrated. | *(fill in during build)* |

---

## Part B — Future work (explicitly out of scope for the event)

| # | Limitation | Why it can't be solved in the event window | Direction for future work |
|---|---|---|---|
| 6 | CloudTrail Lake query cost grows with account/org size | Requires production-scale usage data and a billing feedback loop that doesn't exist in a 4-day sandbox | Scheduled, incrementally-scoped queries (only new events since last run) instead of full re-scans; pre-aggregate into a compact action-resource graph per role, updated incrementally rather than rebuilt each time |
| 7 | Bedrock cost/latency scales with number of roles and CloudTrail history size per role | Needs a multi-role, multi-account test environment to validate | Batch Bedrock calls across structurally similar roles; cache/reuse reasoning for roles with no CloudTrail drift since the last run; only re-invoke Bedrock when drift is detected |
| 8 | Human dry-run approval becomes a bottleneck at org scale (hundreds of roles) | The event demo has exactly one approver and one role — a queue problem only appears at real org scale | Risk-tiering: auto-apply low-risk tightenings (e.g., removing an action with zero observed calls in 90 days); route higher-risk removals to human review, turning a linear approval queue into a triaged one |
| 9 | Design implicitly assumes a single AWS account/region | Multi-account CloudTrail aggregation requires AWS Organizations-level access not available in a personal hackathon account | Central policy-recommendation store (e.g., DynamoDB table keyed by account + role) fed by Organizations trail aggregation, with Verified Permissions acting as one shared verification layer across accounts |

---

## Section for the final writeup

> "Cedar Sentinel's dry-run-and-approve design is intentional, not a stopgap: Bedrock's
> policy suggestions are treated as a draft, not a decision. Cedar/Verified Permissions
> checks internal logical soundness before a human ever sees the diff, but functional
> correctness for the specific workload still depends on the developer's approval step.
> At event scale, we validated this loop against a single role with a controlled usage
> pattern. Scaling this to a real organization — cost-bounded CloudTrail queries, batched
> Bedrock reasoning, risk-tiered auto-approval, and multi-account aggregation — is the
> clearly scoped next phase, not something this build claims to have solved."

---

*Cross-reference: `docs/architecture.md` for the deviation log, `00-master-blueprint.md`
Section 7 for judging alignment, and `docs/ai-tool-disclosure.md` for what AI tooling was
used to reason through these mitigations.*
