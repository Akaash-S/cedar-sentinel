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

**Cedar Sentinel:** Intercepts every `terraform apply` via the Go proxy, so each deploy
cycle is checked against fresh CloudTrail telemetry from the *previous* cycle. This
does not gate the very first deploy of a role — there is no usage data yet to justify
narrowing anything at that point — but it closes the loop on every subsequent apply,
catching permission drift automatically as it happens rather than requiring a
scheduled or manual audit.

> **Correction note:** an earlier version of this pitch claimed policies are tightened
> "before the code ever reaches production." That's inaccurate — CloudTrail data can
> only exist after a role has already run with its originally requested policy. The
> accurate claim is a continuous tightening loop across deploy cycles, not a
> pre-deployment gate.

**Demo strategy (confirmed):** The video starts mid-stream from a pre-provisioned role
that already has a broad policy (e.g. `s3:*` on a bucket) with pre-seeded CloudTrail
Lake usage history already in place — it does not show a live first-deploy-then-wait
sequence, since CloudTrail's native telemetry lag (5–15 minutes) would eat roughly half
the 3-minute slot. The CLI trigger (`cedar-sentinel analyze --role-arn ...`) reads the
pre-seeded history and produces the "Before (Wildcard) vs. After (Cedar
Least-Privilege)" diff on screen immediately. This preserves the broad-to-tight
narrative without the pacing cost of a real wait.

**Continuous loop — build vs. narration (confirmed):** What's actually built for Phase
2 is the Go CLI invoked twice by hand: once to generate/apply the initial policy, once
again after a subsequent IaC change or new API call, to show drift detection. The
always-on version is not built. Narration should say exactly this: *"In our demo
environment, we trigger the analysis loop via the CLI proxy. The underlying
event-driven design — EventBridge rule patterns routing continuous CloudTrail telemetry
into SQS — is architected for background evaluation."* This states the real build
honestly while crediting the architecture for being designed to extend to
always-on, rather than claiming a managed daemon exists.

---

## 2. Native Cedar Policy Generation vs. Legacy IAM JSON

**The competition:** Almost all existing solutions default strictly to traditional AWS
IAM JSON documents, which become dense and difficult to audit as policies accumulate
conditions and exceptions at scale.

**Cedar Sentinel:** Synthesizes Cedar authorization policies natively for AWS Verified
Permissions before ever translating down to IAM JSON. Cedar's policy language is
human-readable and formally analyzable — schema-validated and checked for
contradictions — which is the modern standard for fine-grained authorization and a
genuine structural upgrade over opaque IAM JSON.

---

## 3. Closed-Loop Safeguard Against Workload Lockouts

**The competition:** Automated least-privilege generators risk stripping away
operations that simply haven't appeared in recent telemetry — a role that calls a
given API only monthly can look "unused" in a short observation window — silently
breaking application workloads on the next deploy.

**Cedar Sentinel:** Combines Bedrock's generative drafting with a deterministic
verification step. Before any tightened policy is ever surfaced, the system asserts
that 100% of the actions observed in the CloudTrail Lake sample remain allowed under
the proposed policy. The result is presented as a dry-run diff requiring explicit
developer sign-off — the AI never applies anything unilaterally.

**Failure behavior (confirmed):** If the coverage check fails — Bedrock's draft omits
an action that was genuinely observed in CloudTrail — the CLI **hard-blocks** the
deployment rather than silently falling back. It exits non-zero (`STATUS: RISK
DETECTED`) and surfaces the specific dropped action with its observed call count,
e.g.:

```
[WARNING] SAFETY CHECK FAILED: Potential Workload Lockout Detected!
The proposed Cedar policy drops observed CloudTrail actions:
  - s3:GetObject (Observed 142 times in last 7 days)

Action Taken: Deployment blocked.
[1] Fall back to original policy
[2] Force-apply draft Cedar policy (Override)
[3] Re-evaluate with tighter prompt context
```

A silent auto-fallback would hide the failure and leave the security gap unaddressed;
surfacing it as a blocking, explicit choice demonstrates a deterministic guardrail
against AI hallucination rather than a tool that quietly papers over its own mistakes.

---

## Summary table (for the writeup)

| Differentiator | Competitor approach | Cedar Sentinel approach |
|---|---|---|
| Timing | One-time, on-demand snapshot | Continuous, per-deploy-cycle recheck |
| Policy format | AWS IAM JSON | Cedar (Verified Permissions), then translated to IAM |
| Lockout risk | Usage-window blind spots can silently break workloads | Deterministic 100%-coverage check + human dry-run sign-off before anything applies |

---

## Confirmed decisions log

| Question | Decision | Owner action needed |
|---|---|---|
| First-deploy demo pacing | Start mid-stream from a pre-seeded, already-running role. No live first-deploy-then-wait sequence in the video. | Seed the CloudTrail Lake usage history for the demo role early (Day 1–2), not Day 4 |
| Continuous loop: build vs. narration | CLI triggered twice by hand in Phase 2; always-on daemon is *not* built. Narration credits the EventBridge/SQS architecture as designed for background evaluation, without claiming it's running that way today. | Phase 2 instruction doc should explicitly scope "manual double-trigger demo," not an always-on watcher, to avoid scope creep |
| Lockout-check failure handling | Hard-block with non-zero exit + explicit developer choice (`[1] fallback / [2] override / [3] re-evaluate`). No silent auto-fallback. | This is new Lambda/CLI logic not yet in `phase-01-setup.md` — needs to be written into the Phase 2 instruction doc explicitly |
