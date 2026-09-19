<!-- Intended repo path: instructions/phase-02-core-logic.md -->
# Instruction Document 2 — Phase 2: Core Reasoning & Verification Logic
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, via `00-master-blueprint.md`
**Event day this maps to:** Friday, Sep 18, 2026
**Branch:** `phase-2-core-logic` (off `main`, after `v0.1-setup`)
**Tag on completion:** `v0.2-core-reasoning`
**Response goes to:** `responses/phase-02-response.md`
**Standing rules:** `docs/git-workflow-guardrails.md` still applies unchanged — you commit
and push; you do not merge into `main` and you do not create the tag. Wait for review.

---

## 0. Objective & Scope

Phase 1 proved the pipes connect. Phase 2 makes the middle of the pipeline actually
reason about a policy — but stops short of ever touching a real IAM policy.

**In scope:**
- Lambda: scoped CloudWatch Logs Insights query for a specific role's observed API
  calls, aggregated into a compact action→count map.
- Bedrock: a single reasoning call that drafts a tightened Cedar policy + rationale
  from the diff between the requested policy and the observed-actions map.
- The coverage/lockout hard-block check (Section 5) — new logic, not yet built anywhere.
- Cedar formal verification: schema definition + static/schema validation of the draft
  — **not** a live `CreatePolicy` call against the real policy store (see Section 6).
- A minimal results hand-back mechanism so the CLI can show what Lambda produced
  (Section 2) — the async pipeline has no return path yet; this phase adds one.
- CLI: extend `analyze` to publish, poll, and print a before/after diff.

**Explicitly out of scope — do not build any of this yet:**
- No IAM JSON translation.
- No `iam:PutRolePolicy` call, dry-run or otherwise.
- No dashboard work beyond the Phase 1 placeholder.
- No live `verifiedpermissions.CreatePolicy` against a real, persistent policy store.

If you find yourself writing code that applies anything to a real IAM role, stop —
that's Phase 3.

---

## 1. Pre-flight checklist (human confirms before agent proceeds)

- [ ] Bedrock model access confirmed for `global.anthropic.claude-sonnet-4-6`
      (Global cross-Region inference profile) in the account
- [ ] Dev IAM policy updated: `bedrock:InvokeModel` scoped to the inference-profile ARN
- [ ] Confirmed whether Amazon Verified Permissions is available in the project's
      region (`aws verifiedpermissions list-policy-stores --region <region>`) — if not,
      decide now: call AVP from a different region, or use the local Cedar CLI/analyzer
      exclusively for this phase. Don't discover this mid-build.
- [ ] `v0.1-setup` tag exists on `main`; Amplify (GitHub-connected) app is live
- [ ] Cedar CLI/analyzer available locally, or the disposable-policy-store fallback
      from `cedar-sentinel-research-brief.md` Section 3 is the confirmed path instead

---

## 2. Design decision: getting Lambda's result back to the CLI

The EventBridge → SQS → Lambda pipeline is fire-and-forget by design — there's no
return path today. Add one, using the simplest mechanism that still credits the
event-driven architecture honestly:

1. CLI generates a `request_id` (UUID4) when it publishes the analysis event.
2. Lambda writes its full result to a new DynamoDB table, `cedar-sentinel-results`,
   keyed by `request_id`: the observed-actions map, Bedrock's draft policy + rationale,
   the coverage-check verdict, and the Cedar validation verdict. A `status` field moves
   `PROCESSING` → `COMPLETE` / `BLOCKED` / `ERROR`.
3. CLI polls `get_item` on that table every 2 seconds, 30-second timeout, after
   publishing — then renders the result once `status` leaves `PROCESSING`.
4. In the same write, include a `stage_timings` array: a start/end timestamp pair for
   each of Lambda's four internal stages (CloudWatch query, Bedrock call, coverage
   check, Cedar validation). This is not a separate write and does not change the
   polling behavior above — it's four extra timestamp pairs bundled into the one
   result write that already happens at completion. Phase 2 only records these
   timings; nothing in this phase consumes them. Phase 3's dashboard uses
   `stage_timings` to replay the run stage-by-stage with real recorded durations
   instead of a single "done" flag — that's the only reason this field exists, so
   don't build anything beyond capturing it here.

This is a genuine architectural addition, not a workaround — log it as a new component
in `docs/architecture.md`, not a deviation (nothing it replaces was specified before).

---

## 3. CloudWatch Logs Insights baseline query (Lambda)

- Parameterize the Phase 1 validated query pattern by the target role's ARN
  (`userIdentity.arn`) and a lookback window (7 days is a reasonable default for the
  demo's seeded usage history).
- Aggregate into `{action: count}` — Lambda hands Bedrock this compact map, never raw
  log rows (per the blueprint's context-window-overflow mitigation).

**Acceptance check:** query returns real observed actions for the seeded demo role,
correctly aggregated.

---

## 4. Bedrock reasoning call

- Model: the inference-profile ARN for `global.anthropic.claude-sonnet-4-6`.
- Inputs: the requested IAM policy (already extracted by the Phase 1 CLI/EventBridge
  path) and the observed-actions map from Section 3.
- Require a structured (JSON) response: a proposed Cedar policy + a short rationale —
  not freeform prose, so the Lambda can parse it deterministically.
- Cap `max_tokens` conservatively (~1K output is enough per the research brief's cost
  estimate) — this is a cost-discipline requirement, not a suggestion.

**Acceptance check:** a real call against a seeded role returns a parseable draft
policy + rationale, logged in CloudWatch for inspection.

---

## 5. Coverage / lockout hard-block check (new logic — build this exactly as specified)

Per `docs/differentiators.md`'s confirmed failure behavior:

1. Before Cedar verification, compare the observed-actions map (Section 3) against the
   actions Bedrock's draft policy allows.
2. If any observed action with a nonzero count is missing from the draft: **do not
   proceed to Cedar verification.** Write `status: BLOCKED` to the results table with
   the dropped action(s) and their observed counts.
3. The CLI, on seeing `BLOCKED`, prints the exact warning format below and exits
   non-zero:
   ```
   [WARNING] SAFETY CHECK FAILED: Potential Workload Lockout Detected!
   The proposed Cedar policy drops observed CloudTrail actions:
     - <action> (Observed <N> times in last 7 days)

   Action Taken: Deployment blocked.
   [1] Fall back to original policy
   [2] Force-apply draft Cedar policy (Override)
   [3] Re-evaluate with tighter prompt context
   ```
4. Wire `[1]` (print the original requested policy, exit 0) and `[3]` (re-invoke
   Bedrock with the dropped action explicitly called out in the prompt) for real this
   phase. `[2]` can be a stub — print "not available until IAM enforcement exists in
   Phase 3" and exit non-zero — since there's nothing to force-apply yet.

**Acceptance check:** deliberately craft one test case where Bedrock's draft drops an
observed action, and confirm the hard-block path fires exactly as above — not just the
happy path.

---

## 6. Cedar formal verification — schema + static validation only

- Define a Cedar schema for this project's entity/action model (principal = role,
  action, resource) and register it via `verifiedpermissions.PutSchema` with
  `validationSettings.mode = STRICT`.
- Validate Bedrock's draft policy against that schema using the Cedar CLI/analyzer
  locally, or an isolated disposable policy store if the local analyzer path doesn't
  pan out — **not** `CreatePolicy` against your real, persistent policy store, since
  that call stores the policy on success and isn't a dry-run (confirmed in
  `cedar-sentinel-research-brief.md` Section 3).
- Record the pass/fail verdict and any contradiction messages in the results table.

**Acceptance check:** a deliberately contradictory or schema-violating test policy is
correctly rejected; a valid one passes — without ever mutating the real policy store.

---

## 7. CLI changes

- `analyze --plan-file <path> --role-arn <arn>`: unchanged extraction logic from
  Phase 1, now also generates a `request_id`, publishes the event, polls the results
  table (Section 2), and prints a before/after diff of requested vs. drafted policy
  plus the Cedar verdict.
- Still no `--apply` flag — this phase only ever prints.

**Acceptance check:** one full manual run, from `analyze` invocation to a printed diff,
completes without a stack trace.

---

## 8. Definition of Done — Phase 2 Acceptance Criteria

- [ ] Lambda queries CloudWatch Logs Insights for a real seeded role and aggregates
      correctly
- [ ] Bedrock call returns a structured, parseable draft policy + rationale
- [ ] Coverage check correctly triggers the hard-block path in a deliberately
      constructed failing test case
- [ ] Cedar schema registered via `PutSchema`; draft policy validated without mutating
      the real AVP policy store
- [ ] Results hand-back (DynamoDB + CLI polling) works end-to-end
- [ ] Result item includes a `stage_timings` array with start/end timestamps for all
      four internal stages
- [ ] CLI prints a legible before/after diff for a full run
- [ ] `docs/architecture.md` updated: new DynamoDB results-table component logged, any
      new deviations logged
- [ ] `docs/ai-tool-disclosure.md` updated with today's entry
- [ ] Pre-push secret/PII scan run and reported (per `docs/git-workflow-guardrails.md`)
- [ ] PR opened against `main` — **not merged**

---

## 9. Handoff note to Phase 3

Phase 3 (Sat, Sep 19) adds: translation of the verified Cedar policy into real IAM
JSON, IAM Access Analyzer's `ValidatePolicy` as the second safety net, the dry-run diff
+ explicit approval UI, and the actual `iam:PutRolePolicy` call with retry/backoff for
throttling and eventual-consistency propagation. Phase 2 deliberately stops at
"verified draft" — nothing it produces is ever applied to a real IAM role yet.

---

## Response

**Once this phase is complete, the agent's report goes in `responses/phase-02-response.md`,
using the template already created there — do not write the response inline here.**
