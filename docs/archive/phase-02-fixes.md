<!-- Intended repo path: instructions/phase-02-fixes.md -->
# Instruction Document 2b — Phase 2 Fixes: Pre-Merge Hardening
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, via `00-master-blueprint.md` and a review of `responses/phase-02-response.md` +
`phase-02-complete-chronicle.md` against `instructions/phase-02-core-logic.md`
**Event day this maps to:** still inside the Sep 18–19 window — resolve before Phase 3 starts
**Branch:** `phase-2-core-logic` (stay on the existing branch — nothing has merged yet, no need to branch off it)
**Tag on completion:** `v0.2-core-reasoning` — do **not** tag until every box in Section 7 is checked
**Response goes to:** `responses/phase-02-fixes-response.md`
**Standing rules:** `docs/git-workflow-guardrails.md` still applies unchanged — commit and push, do not merge
into `main`, do not create the tag. Wait for review.

---

## 0. Objective & Scope

Phase 2's own response docs are internally consistent, but a review against the original instruction
document surfaced five real gaps: the demo test run may have analyzed Cedar Sentinel's own execution role
instead of an independent workload role, the Bedrock call may be running on a silent fallback model instead
of Claude, the Lambda execution role's own permissions are wider than the project's least-privilege pitch
allows, and two of Phase 2's acceptance criteria were never actually exercised by a real test. This document
closes those five gaps. Nothing here is new product scope — it's hardening what Phase 2 already claims to
have done.

**Explicitly out of scope for this pass** (still Phase 3, not now):
- No IAM JSON translation, no `iam:PutRolePolicy`, no dashboard work.

If a fix here reveals a problem that actually requires touching real IAM enforcement, stop and flag it rather
than reaching into Phase 3 scope to patch around it.

---

## 1. Pre-flight checklist (human confirms before agent proceeds)

- [ ] Bedrock Anthropic model access confirmed working in the console — no more `INVALID_PAYMENT_INSTRUMENT`
- [ ] Confirmed which single AWS region is now authoritative for every resource (Bedrock, CloudWatch Logs,
      DynamoDB, AVP)
- [ ] Confirmed whether a dedicated demo/test role — distinct from the Lambda execution role — already
      exists with seeded CloudTrail history; if not, one will be provisioned before this doc's Section 2 work
      is re-tested

**Agent: wait for explicit confirmation on all three before running any of the re-tests below.**

---

## 2. Confirm and fix the analysis target

1. Check exactly which `--role-arn` was passed in Test Run C (`full-scope-plan.json`). If it resolves to the
   Lambda's own execution role, that's the root problem — this pipeline was analyzing itself, not a workload.
2. Add a defensive guard in the CLI: if `--role-arn` matches the Lambda execution role's ARN (read from an
   env var or SSM), print
   ```
   [WARNING] Target role matches Cedar Sentinel's own execution role — results will reflect
   the tool's own AWS calls, not a real workload.
   ```
   and require an explicit `--allow-self-analysis` flag to proceed. Default behavior should refuse and exit
   non-zero.
3. Root-cause the mislabeled actions in Test Run C's draft policy — `ssm:PutSchema`, `ssm:CreatePolicy`,
   `ssm:GetPolicyStore`, `ssm:CreatePolicyStore` are actually `verifiedpermissions:*` actions, not `ssm:*`.
   Check whether this is a `stage_cloudwatch_query` parsing bug (wrong `eventSource` field) or a Bedrock
   hallucination in `stage_bedrock_call`. Fix at the source, not by re-labeling after the fact.
4. Once the target-role guard and the mislabeling bug are both fixed, re-run the happy path against a
   genuine, independent demo role and confirm the resulting policy actually makes sense for that role's
   workload.

**Acceptance check:** a fresh happy-path run against a confirmed non-self role produces a draft policy with
correctly-labeled, plausible actions for that role.

---

## 3. Confirm the real invoked model

1. Log the actual `ModelId` returned in each Bedrock response's metadata — not just which model was
   requested — and surface it in the CLI's printed diff, e.g. `Reasoned by: <model-id>`.
2. Add a loud CloudWatch log line, `FALLBACK MODEL USED: <model-id>`, whenever `stage_bedrock_call` falls
   back away from Claude, so this can never be silently missed again.
3. Once Bedrock access is confirmed fixed in the console (Section 1), re-run the happy path and confirm the
   log/CLI output shows the Claude model, not Llama or Mistral.
4. Keep the fallback code itself — it's a legitimate resilience feature — but the actual demo/submission run
   must show Claude as the model that served the request.

**Acceptance check:** a real run's output explicitly names the model that served it, and that model is
Claude for the run being treated as the reference result.

---

## 4. Scope Lambda's own IAM permissions down

1. In `infra/template.yaml`, replace the wildcard `verifiedpermissions:*` statement with only the specific
   actions `stage_cedar_validation` actually calls (`PutSchema`, `CreatePolicy`, `DeletePolicy`,
   `GetPolicyStore`, and anything else genuinely used), scoped via `Resource` to the disposable policy
   store's ARN — never `Resource: "*"`.
2. Remove `aws-marketplace:*` from the Lambda execution role entirely unless Lambda's own runtime code
   makes a specific Marketplace API call (it almost certainly doesn't — the payment-instrument issue is an
   account billing/subscription concern, not something Lambda needs a permission for). Confirm and remove.
3. Re-deploy via `sam deploy` and re-run the happy path to confirm the pipeline still works end-to-end after
   tightening.

**Acceptance check:** Lambda's execution role in the IAM console shows scoped, resource-limited statements
for AVP; no `aws-marketplace:*` remains unless a genuine runtime call justifies it; pipeline still passes.

---

## 5. Exercise the two untested acceptance paths

1. **Cedar rejection path (Section 6 of the original instruction doc — never actually tested):** hand-craft
   one deliberately schema-violating Cedar policy string (reference an action or resource type absent from
   the registered schema) and feed it directly into `stage_cedar_validation`'s validation call, bypassing
   Bedrock for this one test. Confirm the validation call reports it as invalid with a real contradiction/
   violation message, and that this surfaces correctly in both the results table and the CLI's printed
   output.
2. **Option `[2]` stub (never triggered in either test run):** reuse the Test Run A hard-block fixture and
   select `[2]` at the interactive menu. Confirm it prints exactly "not available until IAM enforcement
   exists in Phase 3" and exits non-zero.

**Acceptance check:** both paths have real, logged test evidence — not just "should work by inspection."

---

## 6. Close the documentation loop

1. Add the two Phase 2 deviations — disposable AVP policy store vs. local Cedar CLI, and the Bedrock
   multi-model fallback — into `docs/architecture.md`'s actual deviation log table, dated Sep 18, 2026. The
   response docs describe them; the canonical table doesn't have them yet.
2. Update `docs/aws-console-setup.md` Step 2's reference IAM policy JSON so it matches whatever the real,
   tightened `cedar-sentinel-dev-policy` / Lambda execution role looks like after Section 4 — don't leave
   that doc describing a policy that no longer matches what's deployed.
3. Add a dated row to `docs/ai-tool-disclosure.md` for this fix pass.

---

## 7. Definition of Done — Acceptance Criteria for this document

- [ ] Confirmed the reference demo run analyzes a genuine external role, not Cedar Sentinel's own execution
      role — logged with the actual role ARN used
- [ ] Mislabeled `ssm:*` / `verifiedpermissions:*` action bug root-caused and fixed
- [ ] CLI/logs show which model actually served the Bedrock call; a real run against Claude (not the
      fallback) is captured as the reference result
- [ ] Lambda execution role's `verifiedpermissions:*` scoped to the disposable store's ARN;
      `aws-marketplace:*` removed unless justified by an actual runtime call
- [ ] Cedar rejection path tested with a deliberately invalid policy — confirmed rejected
- [ ] Option `[2]` stub tested — confirmed correct message + non-zero exit
- [ ] `docs/architecture.md` deviation table updated with dated entries for both Phase 2 deviations
- [ ] `docs/aws-console-setup.md` Step 2 IAM JSON reconciled with the real deployed policy
- [ ] `docs/ai-tool-disclosure.md` updated with today's entry
- [ ] Pre-push secret/PII scan re-run and reported
- [ ] Still on branch `phase-2-core-logic`, still not merged to `main`, no tag applied

---

## 8. Handoff note

Once every box above is checked and reviewed, `phase-2-core-logic` can be merged to `main` and tagged
`v0.2-core-reasoning`, and Phase 3 (IAM translation, Access Analyzer validation, dry-run approval UI,
`iam:PutRolePolicy`) can begin on schedule.

---

## Response

**Once this document is complete, the agent's report goes in `responses/phase-02-fixes-response.md`,
mirroring the existing response template — do not write the response inline here.**
