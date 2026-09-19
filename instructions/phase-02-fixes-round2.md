<!-- Intended repo path: instructions/phase-02-fixes-round2.md -->
# Instruction Document 2c — Phase 2 Fixes: Deployment Verification & Status Bug
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, via a live CloudWatch log from `RequestId: 5b4a2a35-3f70-4559-ab42-cb3c3a7d5d4b`
reviewed against `responses/phase-02-fixes-response.md`
**Event day this maps to:** still inside the Sep 18–19 window — resolve before Phase 3 starts
**Branch:** `phase-2-core-logic` (stay on the existing branch — still not merged, no need to branch off it)
**Tag on completion:** `v0.2-core-reasoning` — do **not** tag until every box in Section 6 is checked
**Response goes to:** `responses/phase-02-fixes-round2-response.md`
**Standing rules:** `docs/git-workflow-guardrails.md` still applies unchanged — commit and push, do not merge
into `main`, do not create the tag. Wait for review.

---

## 0. Objective & Scope

`responses/phase-02-fixes-response.md` claimed the Nova Lite switch (Section 3) and the eventSource
mislabeling fix (Section 2) were both complete, but neither had a real run attached as evidence — both
acceptance checks were written in future/descriptive tense, not backed by actual output.

A real Lambda invocation (log attached below) confirms the concern was justified, and surfaced one further
bug:

1. **The Nova Lite switch is not actually live.** The log shows `Invoking Bedrock model
   'global.anthropic.claude-sonnet-4-6'` — the exact pre-fix behavior, followed by the same
   `INVALID_PAYMENT_INSTRUMENT` failure and Llama fallback the fix was supposed to eliminate. Either the code
   change was never deployed (`sam deploy` not re-run), or this invocation ran against a stale Lambda
   version.
2. **New bug: a failed Cedar validation is written to DynamoDB as `status: COMPLETE`.** The log shows `Cedar
   validation FAILED: ValidationException — Invalid input` immediately followed by `Result written ... with
   status 'COMPLETE'`. A developer running the CLI would see COMPLETE and reasonably assume the draft policy
   passed verification, when it didn't.
3. **Root cause of that validation failure:** with zero observed actions (this demo role has no CloudTrail
   history yet), Bedrock's fallback model drafted `"cedar_policy": "deny all;"` — not valid Cedar syntax,
   which is why AVP rejected it. The "deny everything by default" intent is reasonable; the syntax it was
   expressed in is not.

This document closes all three gaps. Nothing here is new product scope.

**Explicitly out of scope for this pass** (still Phase 3, not now):
- No IAM JSON translation, no `iam:PutRolePolicy`, no dashboard work.

---

## 1. Pre-flight checklist (human confirms before agent proceeds)

- [ ] `demo-role` has real, seeded CloudTrail activity within the 7-day lookback window — see Section 4 below
      for the exact commands; without this, Stage 1 will keep returning 0 observed actions and none of the
      re-tests below will be meaningful
- [ ] Confirmed which Lambda alias/version was actually invoked in the attached log (check whether
      `$LATEST` was deployed after the Section 3 code change, or before)

**Agent: wait for confirmation on both before running the re-tests in Sections 2 and 3.**

---

## 2. Confirm the Nova Lite switch is actually deployed

1. Run `sam build && sam deploy` on the current branch state. Do not assume a prior deploy already shipped
   this — the attached log is direct evidence it didn't.
2. After deploy, check the Lambda's actual configuration (console: **Configuration → Environment variables**,
   or `aws lambda get-function-configuration --function-name <name> --query 'Environment.Variables.BEDROCK_MODEL_ID'`)
   and confirm it reads `apac.amazon.nova-lite-v1:0`. If it still shows the old value, the `samconfig.toml`
   parameter override or the SAM parameter default from the previous fix pass did not actually take — find
   out why before re-testing.
3. Add a permanent safety net: log the resolved `BEDROCK_MODEL_ID` value at the very start of
   `stage_bedrock_call`, before any invocation is attempted — e.g. `logger.info("Resolved BEDROCK_MODEL_ID: %s", model_id)`.
   This makes a future stale-deploy mismatch visible immediately, without having to infer it from which model
   the invocation log happens to name.
4. Re-run the pipeline (real SQS-triggered run, not a synthetic unit test) and confirm the log shows
   `BEDROCK MODEL USED: apac.amazon.nova-lite-v1:0` — no `INVALID_PAYMENT_INSTRUMENT`, no fallback warning.

**Acceptance check:** a real CloudWatch log, pasted into the response doc, showing Nova Lite invoked
successfully on the first attempt.

---

## 3. Fix the false `COMPLETE` status on Cedar validation failure

1. In `write_result` (or wherever the final status is decided), when `stage_cedar_validation` returns an
   invalid/rejected verdict, write a distinct status — e.g. `CEDAR_INVALID` — not `COMPLETE`. Include the
   actual `ValidationException` message and the offending Cedar policy text in the result item.
2. Update the CLI's result renderer to handle this status explicitly: print something like
   `[FAIL] Cedar formal verification rejected the draft policy`, show the validation error, and exit
   non-zero. This must read distinctly from both `BLOCKED` (coverage-check failure) and `COMPLETE` (genuine
   success) — a developer needs to be able to tell all three apart at a glance.
3. Note that `lambda/test_cedar_rejection.py` from the previous fix pass calls `stage_cedar_validation`
   directly and never touches `write_result`, so it did not — and could not — have caught this. This fix
   needs its own end-to-end check: run the full pipeline (SQS trigger → Lambda → DynamoDB → CLI) against a
   case that fails Cedar validation, and confirm the status written and printed is `CEDAR_INVALID`, not
   `COMPLETE`.

**Acceptance check:** a real end-to-end run that fails Cedar validation shows `CEDAR_INVALID` in both
DynamoDB and the CLI output — not `COMPLETE`.

---

## 4. Fix the zero-observed-actions Cedar syntax + seed real activity

1. Update the Bedrock system prompt (used in `stage_bedrock_call`) to handle the zero-observed-actions case
   explicitly: when the observed-actions map is empty, the model must emit syntactically valid Cedar that
   denies everything — e.g. a policy with no `permit` statements at all, or whatever the registered schema
   accepts as a valid empty-effect policy — not free-text like `"deny all;"`. Add this as an explicit
   instruction or few-shot example in the prompt, since this is the literal cause of Section 3's bug, not a
   hypothetical.
2. Separately, seed real CloudTrail activity on `demo-role` so future test runs aren't stuck at 0 observed
   actions (which makes the coverage check and the eventSource-prefix fix from the previous pass impossible
   to meaningfully verify). Example, using the demo role's credentials or an assumed-role session:
   ```bash
   aws sts assume-role --role-arn arn:aws:iam::<ACCOUNT_ID>:role/demo-role --role-session-name seed-test
   # export the returned temporary credentials, then:
   aws s3 ls
   aws s3 cp ./test-file.txt s3://<some-test-bucket>/test-file.txt
   aws s3 rm s3://<some-test-bucket>/test-file.txt
   ```
   Allow CloudTrail-to-CloudWatch delivery lag (a few minutes) before re-running the pipeline against this
   role.
3. Re-run the pipeline against `demo-role` now that it has real activity, and confirm the observed-actions
   map is non-empty and correctly service-prefixed (e.g. `s3:GetObject`, `s3:PutObject`, not bare
   `GetObject`/`PutObject`).

**Acceptance check:** a real run against `demo-role` with non-empty, correctly-labeled observed actions, and
a syntactically valid Cedar policy that passes AVP validation.

---

## 5. Close the documentation loop

1. Log this round's fixes as new dated entries (Sep 19, 2026) in `docs/architecture.md`'s deviation table —
   specifically the deploy-verification gap, the new `CEDAR_INVALID` status, and the zero-actions prompt fix.
2. Add a dated row to `docs/ai-tool-disclosure.md` for this pass.

---

## 6. Definition of Done — Acceptance Criteria for this document

- [ ] Real CloudWatch log attached showing `apac.amazon.nova-lite-v1:0` invoked successfully, no fallback
- [ ] `BEDROCK_MODEL_ID` resolved-value logging added at the top of `stage_bedrock_call`
- [ ] A distinct `CEDAR_INVALID` status implemented, written on Cedar validation failure instead of
      `COMPLETE`, with the validation error and offending policy text attached
- [ ] CLI renders `CEDAR_INVALID` distinctly from both `BLOCKED` and `COMPLETE`, exits non-zero
- [ ] Real end-to-end run (not the isolated unit test) confirms the `CEDAR_INVALID` path works
- [ ] Bedrock prompt updated so a zero-observed-actions case produces syntactically valid Cedar, not
      free-text like `"deny all;"`
- [ ] `demo-role` has real, seeded CloudTrail activity; a fresh run shows non-empty, correctly-prefixed
      observed actions
- [ ] `docs/architecture.md` and `docs/ai-tool-disclosure.md` updated with dated entries for this pass
- [ ] Still on branch `phase-2-core-logic`, still not merged to `main`, no tag applied

---

## 7. Handoff note

Once every box above is checked and backed by a real, pasted log (not a description of expected behavior),
`phase-2-core-logic` can be merged to `main` and tagged `v0.2-core-reasoning`, and Phase 3 can begin on
schedule.

---

## Response

**Once this document is complete, the agent's report goes in `responses/phase-02-fixes-round2-response.md`,
mirroring the existing response template — do not write the response inline here. Every acceptance check in
this document requires pasted, real log output — a description of what should happen is not sufficient
evidence, per the gap this document itself exists to close.**
