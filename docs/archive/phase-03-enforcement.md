<!-- Intended repo path: instructions/phase-03-enforcement.md -->
# Instruction Document 3 — Phase 3: IAM Translation & Enforcement
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, via `00-master-blueprint.md` Section 6 (steps 6–9) and Section 9 timeline
**Event day this maps to:** Saturday, Sep 19, 2026
**Branch:** `phase-3-enforcement` (off `main`, after `v0.2-core-reasoning`)
**Tag on completion:** `v0.3-enforcement`
**Response goes to:** `responses/phase-03-response.md`
**Standing rules:** `docs/git-workflow-guardrails.md` still applies unchanged — you commit and push; you do
not merge into `main` and you do not create the tag. Wait for review. (If the file is not at that path,
look for it at `instructions/git-workflow-guardrails.md` — earlier phase docs referenced both.) Every
acceptance check in this document requires pasted, real log/output evidence — a description of expected
behavior is not sufficient, per the standard the last two fix rounds established. Redact account IDs and
real ARNs in pasted evidence (`<ACCOUNT_ID>`) exactly as in prior response docs.

**Revision note (Sep 19, 2026 — pre-send review):** This version patches the first draft after a review
against what Phase 2 actually produced. Changes: (a) new Section 0.1 pinning down *where each step runs*
(Lambda vs. CLI); (b) CloudTrail `eventName` → IAM action mapping added to the translator (Section 2) —
Phase 2 output contains `s3:ListBuckets`, which is not a valid IAM action; (c) Resource assignment no longer
defaults to `*` when ambiguous; (d) `CheckNoNewAccess` promoted from optional to required (Section 3) —
Phase 2's Cedar schema is generated from the draft's own actions, so it cannot detect privilege escalation;
(e) target policy-name handling, pre-apply snapshot, and a demo-role reset script (Section 5) — the demo role
carries an inline policy whose name differs from the Terraform fixture's, so an unguarded `PutRolePolicy`
would add a parallel policy and tighten nothing; (f) explicit decision on lockout-menu option `[2]`
(Section 4); (g) self-apply guard; (h) new/adjusted statuses; (i) audit-store schema and failure semantics;
(j) dashboard default changed to a static recorded-run snapshot (Section 8); (k) required limitations-doc
entries (Section 9).

---

## 0. Objective & Scope

Phase 2 stops at a verified Cedar draft — nothing it produces ever touches a real IAM role. Phase 3 closes
the loop: translate that verified Cedar policy into real IAM JSON, run a second independent safety check,
show the developer an explicit dry-run diff, get explicit approval, and only then apply it.

**In scope:**
- Cedar → IAM JSON translation, including CloudTrail-eventName → IAM-action normalization (Section 2).
- IAM Access Analyzer `ValidatePolicy` **and** `CheckNoNewAccess` as a second, independent safety net after
  Cedar verification (Section 3).
- A dry-run diff + explicit developer approval step, CLI-driven (Section 4).
- The real `iam:PutRolePolicy` call, with pre-apply snapshot, retry/backoff and read-back verification
  (Section 5), plus a demo-role reset script (Section 5.6).
- One deliberate, real `verifiedpermissions.CreatePolicy` call against a **persistent** (non-disposable) AVP
  store, as the audit record — and only after a successful apply (Section 6).
- A minimal, read-only dashboard view (Section 8) — **stretch goal, cut first if time is short.**
- Required limitations-doc updates (Section 9).

**Explicitly out of scope for Phase 3:**
- No auto-apply or scheduled re-checks — every run here is one full, developer-triggered pass, start to
  finish, same as Phase 2.
- No multi-role or multi-account handling (per `docs/limitations-and-mitigations.md` item 9 — future work).
- No Cognito auth on the dashboard.
- No rollback *command* (a snapshot is stored and manual rollback steps are documented — Section 5.3).
- No video/writeup/submission work — that's Phase 4. Per the blueprint's own risk table, features freeze at
  the end of today; don't let dashboard polish eat into core enforcement testing time.

If you find yourself building anything that runs unattended or reapplies policies on a schedule, stop —
that's explicitly future work, not this event.

### 0.1 Where each step runs (binding — do not deviate without flagging)

| Step | Runs in | Credentials / permissions |
|---|---|---|
| Cedar → IAM translation | Lambda (new pipeline stage after Cedar validation) | No new IAM rights beyond what Phase 2 has |
| `ValidatePolicy`, `CheckNoNewAccess` | Lambda (new pipeline stage) | Add `access-analyzer:ValidatePolicy` and `access-analyzer:CheckNoNewAccess` to the Lambda execution role. These do not support resource-level scoping, so `Resource: "*"` is unavoidable here — note this in `docs/architecture.md` as a justified exception, not an oversight |
| Diff, approval prompt, `PutRolePolicy`, `GetRolePolicy` read-back | **CLI** | Dev user (`cedar-sentinel-dev`), which is already scoped to `role/cedar-sentinel-*` |
| Audit `CreatePolicy` on the persistent store | **CLI** | Dev user |
| Final status update to the results table | CLI (`dynamodb:UpdateItem`) | Dev user |

**The Lambda execution role must NOT gain any `iam:Put*`, `iam:Attach*`, `iam:Create*` or similar write
permission in this phase.** An enforcement tool whose own runtime role can rewrite IAM contradicts the
project's least-privilege pitch. If you believe something requires it, stop and flag it.

---

## 1. Pre-flight checklist (human confirms before agent proceeds)

- [x] `v0.2-core-reasoning` tag exists on `main` — confirmed merged and pushed
- [x] IAM permissions confirmed on the **dev user** for: `access-analyzer:ValidatePolicy` and
      `access-analyzer:CheckNoNewAccess` (if the CLI ends up calling them), `verifiedpermissions:CreatePolicyStore`
      / `PutSchema` / `CreatePolicy` / `GetPolicy`, `ssm:GetParameter`/`PutParameter` on `/cedar-sentinel/*`,
      `dynamodb:UpdateItem` on the results table, and `iam:PutRolePolicy` / `GetRolePolicy` /
      `ListRolePolicies` / `ListAttachedRolePolicies` on `cedar-sentinel-*` roles
- [x] Confirmed `cedar-sentinel-demo-role` is the role Phase 3 will apply against — real enforcement testing
      must run against this role, never the Lambda's own execution role
- [x] **Demo-role policy inventory done** (human): output of `aws iam list-role-policies` and
      `aws iam list-attached-role-policies` for the demo role pasted here, with the inline policy name that
      Phase 3 will overwrite written down: `demo-broad-s3`
- [ ] Decided the persistent AVP audit store's name — default `cedar-sentinel-audit-store` — distinct from
      Phase 2's disposable verification-only store
- [x] **Decision — S3 data events:** either (a) human enabled S3 data events on the trail for the demo bucket
      only and re-seeded object-level activity, or (b) not enabled, and the management-events-only blind spot
      will be disclosed in the limitations doc. Choice: `(a)`
- [x] **Decision — dashboard:** default is the static recorded-run snapshot (Section 8). Confirm, or state
      "defer to Phase 4"
- [x] **Decision — lockout menu option `[2]`:** default is "keep disabled, updated message" (Section 4.5).
      Confirm, or state otherwise

**Agent: confirm the unchecked boxes above with the human before proceeding. Where the human has not
answered a "Decision" box, use the stated default and say so in the response doc.**

---

## 2. Cedar → IAM JSON translation

1. Build a translator (new Lambda pipeline stage, after Cedar validation passes) that takes a verified Cedar
   `permit(...)` statement's action list — strings of the form `CedarSentinel::Action::"service:ActionName"` —
   and produces a standard IAM policy document:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["service:ActionName", "..."],
         "Resource": "<see 2.3>"
       }
     ]
   }
   ```
2. **Action normalization (eventName → IAM action).** Phase 2's observed actions come from CloudTrail
   `eventName`, which does not always equal the IAM action name. Known example from a real Phase 2 run:
   the draft contained `s3:ListBuckets`, but the IAM action is `s3:ListAllMyBuckets`.
   - Add a small, hand-curated mapping table (a plain dict in one module, with a comment per entry) for known
     mismatches. Seed it with at least `s3:ListBuckets → s3:ListAllMyBuckets`; add any other mismatch the
     real demo runs surface.
   - Apply the mapping in the translator, so the Cedar policy text is left untouched and the IAM output is
     correct. Record every applied mapping in the results item (`action_mappings_applied`) and print it in the
     dry-run diff, so a human can see what was changed.
   - Do not attempt to build a general eventName→action resolver. A curated table plus Access Analyzer's
     invalid-action detection (Section 3) is the intended design; the limitation goes in the limitations doc
     (Section 9).
3. **Resource assignment.** For each translated action, find the statement in the *originally requested*
   policy whose `Action` list covers it (wildcard-aware: `s3:*` covers `s3:CreateBucket`; `ec2:Describe*`
   covers `ec2:DescribeInstances`). Group actions by that statement's `Resource` value and emit one output
   statement per distinct Resource.
   - If an action is covered by no requested statement, **do not add it and do not default to `"*"`.**
     Exclude it from the output and record it in the results item under `unmatched_actions`. The developer
     sees it in the diff. (Section 3's `CheckNoNewAccess` is the independent backstop.)
   - If that leaves zero actions, treat it as an error state, not an empty policy.
4. Only ever translate `permit` statements into `Allow`. If a `forbid` block somehow reaches this stage,
   treat it as an error and refuse to translate — Phase 2's deterministic guard
   (`_sanitize_and_guard_cedar_policy`) is supposed to guarantee a clean permit-only policy by the time it gets
   here, so a forbid block showing up means that guarantee broke and needs investigating, not silently working
   around.
5. Unit tests (real, runnable, output pasted). At least:
   - one single-action policy;
   - one multi-service multi-action policy;
   - one policy containing `s3:ListBuckets`, confirming it becomes `s3:ListAllMyBuckets` and the mapping is
     recorded;
   - one where an action matches no requested statement, confirming it is excluded and recorded, not widened
     to `*`;
   - one with a `forbid` block, confirming the translator refuses.

**Acceptance check:** a real verified Cedar policy from a live Phase 2 run translates to IAM JSON that
`json.loads` parses cleanly and that a human can visually confirm matches the Cedar policy's intent —
paste input and output.

---

## 3. IAM Access Analyzer — second independent safety net

Context the agent must understand: Phase 2's Cedar schema is generated dynamically from the observed and
draft actions, so Cedar STRICT validation confirms syntax/schema-consistency but **cannot** catch privilege
escalation. Access Analyzer is therefore the only real "no new access" check in the pipeline — hence
`CheckNoNewAccess` is required here, not optional.

1. Before ever reaching the apply step, call `access-analyzer:ValidatePolicy` on the translated IAM JSON with
   `policyType=IDENTITY_POLICY`. Use the same region as the rest of the stack (`AWS_REGION`).
2. Treat any `ERROR`-severity finding as hard-blocking: write a new status, `ANALYZER_INVALID`, to the
   results table with the finding details (`reason: VALIDATION_ERROR`), and do not proceed to the apply step.
   This mirrors the existing `CEDAR_INVALID` pattern — same shape, different stage.
3. Treat `SECURITY_WARNING` / `WARNING` / `SUGGESTION`-severity findings as non-blocking, but store them and
   surface them in the dry-run diff (Section 4) so the developer sees them before approving.
4. **Required:** call `access-analyzer:CheckNoNewAccess` with the translated policy as the new document and
   the originally requested policy as the existing document (`policyType=IDENTITY_POLICY`). If the result
   indicates new access, hard-block with `ANALYZER_INVALID` and `reason: NEW_ACCESS`, including the reasons
   returned. Surface a passing result in the diff too. (Per-call cost is expected to be negligible at demo
   volume — confirm in the console/pricing page and note it in the response doc.)
5. Add `iam_translation` and `analyzer_validation` start/end timestamp pairs to the `stage_timings` array so
   the dashboard timeline (Section 8) covers these stages.
6. Lambda writes the translated policy, the mapping/unmatched records, and all findings into the results
   item. Final status when everything passes stays `COMPLETE` (meaning "verified, awaiting the developer's
   apply decision") — nothing is applied by Lambda.

**Acceptance check — do not presume how Access Analyzer will classify a given input; run it and report what
it actually returns.** Paste real `ValidatePolicy` output for each of:
- (a) a policy with an invalid action name (an `s3:ListBuckets` case, if it fires naturally, or a deliberately
  misspelled action) → confirm `ERROR` → `ANALYZER_INVALID` written to DynamoDB and rendered by the CLI;
- (b) an over-permissive policy (`Resource: "*"` with a wildcard action) → report the severity actually
  returned, and confirm it appears in the dry-run diff as a non-blocking finding *if* it is below `ERROR`;
- (c) a clean, tightly-scoped policy → passes without blocking findings;
- (d) `CheckNoNewAccess` against a translated policy containing an action absent from the requested policy →
  hard-block (`reason: NEW_ACCESS`); and against a normal subset policy → pass.

---

## 4. Dry-run diff + explicit approval (CLI)

1. Extend the `analyze` command with an `--apply` flag and a `--policy-name <name>` argument (required when
   `--apply` is used). Without `--apply`, behavior is unchanged from Phase 2 — print-only, nothing applied.
2. **Guards on `--apply` (refuse and exit non-zero before any prompt):**
   - the target role ARN equals the Lambda execution role ARN (`LAMBDA_EXECUTION_ROLE_ARN`) —
     `--allow-self-analysis` must **never** unlock `--apply`;
   - the role name does not match `cedar-sentinel-*`;
   - the results status is anything other than `COMPLETE` (`BLOCKED`, `CEDAR_INVALID`, `ANALYZER_INVALID`,
     `ERROR`, `PROCESSING` all refuse to prompt).
3. Add a distinct CLI renderer for `ANALYZER_INVALID` (mirroring `_render_cedar_invalid_result`): print
   `[FAIL] IAM Access Analyzer rejected the translated policy`, the reason (`VALIDATION_ERROR` or
   `NEW_ACCESS`), the finding details, and exit non-zero. It must read distinctly from `BLOCKED`,
   `CEDAR_INVALID` and `COMPLETE`.
4. With `--apply` and a `COMPLETE` result:
   - Print a clear before/after diff: originally requested IAM policy vs. the translated tightened IAM
     policy.
   - Print applied action mappings, any `unmatched_actions`, and all non-blocking Access Analyzer findings.
   - Print which inline policy name will be overwritten on the role (Section 5.1).
   - Prompt explicitly: `Apply this policy to <role_arn>? [y/N]`.
5. Only proceed to Section 5 on an explicit `y`. Anything else — including no input, `n`, or Ctrl-C — exits
   cleanly with code 0 and applies nothing; the CLI writes `status: DECLINED` to the results item.
6. **Lockout menu option `[2]` (default decision unless the human states otherwise):** keep it disabled.
   Update the message to: `Override is intentionally disabled in this build: applying a policy that drops
   observed actions bypasses the lockout safeguard. Use [3] to re-evaluate or [1] to fall back.` and exit
   non-zero. Options `[1]` and `[3]` are unchanged. The menu text stays as specified in `docs/differentiators.md`
   so the demo narration can still describe the three-way choice; note the disabled override in the limitations
   doc (Section 9).

**Acceptance check:** one real run where the developer answers `N` — confirm nothing is applied, the CLI
exits 0, and `DECLINED` is recorded; one real run where the developer answers `y` — confirm it proceeds to
Section 5; one real refused run for each guard in 4.2 (paste output).

---

## 5. Enforcement — `iam:PutRolePolicy` with resilience

### 5.1 Target policy name — never silently add a parallel policy
`PutRolePolicy` overwrites by policy name. The demo role's live inline policy (recorded in the Section 1
inventory) may have a different name from the Terraform fixture's. Therefore:
1. Before applying, call `iam:ListRolePolicies` on the target role and confirm `--policy-name` is one of the
   role's **existing** inline policies. If not, refuse with a clear message listing the role's actual inline
   policy names. Do not create a new policy name in this phase.
2. Call `iam:ListAttachedRolePolicies`. After a successful apply, if the role still has other inline policies
   or attached managed policies, print `[WARNING] Role has other policies that may still grant broad access:
   <names>. Effective access is not fully tightened by this change.` and record them in the results item.
   (Do not detach or delete anything — out of scope.)

### 5.2 Apply
1. On explicit approval, call `iam:PutRolePolicy` with the translated policy under `--policy-name`.
2. Wrap the call in exponential backoff retry (e.g. 3 attempts) for `ThrottlingException`.
3. Catch and clearly report — not as a stack trace — `MalformedPolicyDocumentException` (should be rare
   given Access Analyzer already validated, but this is defense-in-depth, not redundant) and
   `LimitExceededException` (inline policy size cap).

### 5.3 Snapshot before overwrite; manual rollback documented
Immediately before `PutRolePolicy`, call `iam:GetRolePolicy` for the same policy name and store the existing
document in the results item as `previous_policy`. No rollback command is built. Document in the README (one
short section) the manual rollback: take `previous_policy` from the results item and `put-role-policy` it back
under the same name.

### 5.4 Read-back
After a successful `PutRolePolicy` call, read the policy back via `iam:GetRolePolicy` and confirm it matches
what was sent (compare parsed JSON, not raw strings — URL-decoding and key ordering can differ). IAM changes
propagate with a short eventual-consistency delay, so retry the read-back a couple of times with a short
backoff before declaring success or failure.

### 5.5 Final status
Write the final status to the results table (from the CLI):
- `APPLIED` — put succeeded and read-back matched;
- `APPLIED_UNVERIFIED` — put succeeded but read-back never confirmed after retries (the policy may well be
  live; report this honestly and tell the developer to check the role manually);
- `APPLY_FAILED` — the put itself failed, with the specific exception recorded.

### 5.6 Demo-role reset script
The demo needs to be repeatable, and after a successful apply the demo role is tight. Add
`scripts/reset_demo_role.py` (or `.sh`):
- Restores `cedar-sentinel-demo-role`'s inline policy to the broad "before" policy from the demo fixture,
  under the inline policy name recorded in the Section 1 inventory.
- **Hard-coded to refuse any role other than `cedar-sentinel-demo-role`.**
- The demo fixture's policy name (`cli/fixtures/demo-role-plan.json`) and the role's live inline policy name
  must match after this script runs, so `analyze --apply --policy-name <name>` overwrites the broad policy
  rather than sitting beside it.
- Paste output showing the role's policy before reset, after reset, and after a subsequent apply.

**Acceptance check:** one real successful apply against `cedar-sentinel-demo-role`, with the read-back
confirming the new policy is live on the role (paste the actual `GetRolePolicy` output), plus
`ListRolePolicies` / `ListAttachedRolePolicies` output after apply showing what else remains on the role.
Also paste one real `apply → reset → apply` cycle to prove repeatability.

---

## 6. Audit trail — the one deliberate `CreatePolicy` call

Per the confirmed decision in `cedar-sentinel-research-brief.md` Section 3: this project makes exactly one
live `CreatePolicy` call against a real, persistent AVP policy store — and only here, only after a
successful apply.

1. Create a new, persistent policy store (default `cedar-sentinel-audit-store`) — separate from Phase 2's
   disposable verification-only store, which remains purely ephemeral and is never used for anything
   permanent. Store its ID in SSM at `/cedar-sentinel/dev/avp-audit-store-id` (never in git). Register a
   schema on it (`PutSchema`, STRICT) before any `CreatePolicy`, built the same way as the Phase 2 schema, so
   the audit write validates.
2. Immediately after a confirmed `APPLIED` status (Section 5.5), the **CLI** writes the approved Cedar
   policy text into this store via `CreatePolicy`, with the rationale and `request_id` in the policy's
   `description` field. This becomes the permanent, queryable audit record of what was approved and why.
3. This call must never fire before an approval, and never fire at all on a `CEDAR_INVALID`,
   `ANALYZER_INVALID`, `BLOCKED`, `DECLINED`, `APPLY_FAILED` or `APPLIED_UNVERIFIED` outcome.
4. If the audit `CreatePolicy` fails after a successful apply, keep the status as `APPLIED`, set
   `audit_failed: true` with the error in the results item, and print a clear warning. Never report an
   applied policy as a failed apply because the audit write failed.

**Acceptance check:** after a real successful apply, the policy is visible in the persistent AVP store via
`GetPolicy` — paste the real output. Also paste evidence that a `DECLINED` run and an `ANALYZER_INVALID` run
wrote nothing to the audit store (e.g. `ListPolicies` before/after).

---

## 7. CLI changes summary

- `analyze --plan-file <path> --role-arn <arn>` — unchanged, print-only (Phase 2 behavior, still the
  default). Now also renders the translated IAM policy, mappings and analyzer findings when present.
- `analyze --plan-file <path> --role-arn <arn> --apply --policy-name <name>` — full Phase 3 flow: guards →
  (results already translated + validated by Lambda) → diff + approval prompt → snapshot → `PutRolePolicy` →
  read-back → status update → audit record.
- `scripts/reset_demo_role.py` — restores the demo role's broad policy for repeatable demos.

Status values in play after this phase: `PROCESSING`, `COMPLETE`, `BLOCKED`, `CEDAR_INVALID`,
`ANALYZER_INVALID`, `DECLINED`, `APPLIED`, `APPLIED_UNVERIFIED`, `APPLY_FAILED`, `ERROR`. Document this list
in `docs/architecture.md`.

---

## 8. Stretch — minimal read-only dashboard view (cut first if short on time)

The Amplify URL is the Ship It deliverable, and today it still shows the Phase 1 placeholder text. Whatever
happens with the rest of this section, that placeholder text must be replaced before submission.

**Default approach (unless the human says "defer"): a static recorded-run snapshot** — no new API surface.
1. Add `scripts/export_run.py <request_id>` that reads one completed item from `cedar-sentinel-results` and
   writes a sanitized `dashboard/run.json` (account IDs, real ARNs, log-group names and store IDs replaced with
   placeholders — this file is committed, so it is subject to the pre-push secret scan).
2. `dashboard/index.html` renders that JSON, clearly labeled as a **recorded run** (not live), showing:
   - the stage-by-stage timeline from `stage_timings` (first real use of that field), including the new
     `iam_translation` and `analyzer_validation` stages;
   - the before/after policy diff, with the final status (e.g. `APPLIED`).
3. Visual direction: terminal/DevOps look — monospace, dark background, git-diff-style red/green lines. Not
   glowing cards or gradients. Readability over decoration.
4. No write actions from the dashboard. Approval stays CLI-only for this event — the dashboard is
   observability only, never a control surface.
5. A live-read version (API Gateway + Lambda reading the results table) is **not** attempted today unless
   Sections 2–6 are fully done and reviewed with real evidence and time clearly remains; it adds IAM/API
   surface. If not attempted, say so in the response doc.
6. If even the static version doesn't comfortably fit before end of day, explicitly punt it to Phase 4 rather
   than letting it compress testing time on Sections 2–6 — but still swap out the placeholder text. Either
   way, say which was decided in the response doc.

**Acceptance check (if attempted):** the Amplify URL shows a real completed run's stage timeline and diff,
not the Phase 1 placeholder text (paste the URL response or a description of what loads, plus the
sanitization check on `run.json`).

---

## 9. Required documentation updates

1. `docs/architecture.md`: new components (translator stage, analyzer stage, audit store, reset script,
   snapshot field), the status list from Section 7, the Lambda `access-analyzer:*` `Resource: "*"` exception
   with its justification, and dated (Sep 19, 2026) deviation entries for anything that differed from this
   document.
2. `docs/limitations-and-mitigations.md`: add these entries, each with a status of `Mitigated`, `Partially
   mitigated` or `Future work — not attempted`:
   - Cedar STRICT validation runs against a schema generated from the draft's own actions, so it validates
     syntax/schema-consistency but cannot detect privilege escalation; `CheckNoNewAccess` is the actual
     escalation check.
   - CloudTrail `eventName` does not always equal the IAM action; a small hand-curated mapping table plus
     Access Analyzer's invalid-action detection is the mitigation; a general resolver is future work.
   - The trail records management events only (unless data events were enabled per Section 1), so
     object-level S3 actions (`GetObject`, `PutObject`, `DeleteObject`) are invisible to the baseline; a
     policy tightened from it could drop object-level access — the workload-lockout risk the tool exists to
     prevent.
   - `iam:PutRolePolicy` failure handling: what is handled (throttling retry, malformed/size errors,
     read-back with eventual-consistency retry, `APPLIED_UNVERIFIED`), what is not (no automated rollback —
     snapshot only, manual steps in the README), and that other attached/inline policies are reported but
     never modified.
   - Lockout-menu option `[2]` (force-apply) is disabled in this build.
3. `docs/ai-tool-disclosure.md`: dated row for today.
4. `docs/differentiators.md`: note the disabled `[2]` override so the demo narration stays honest (the human
   will finalize wording — just flag it).

---

## 10. Definition of Done — Phase 3 Acceptance Criteria

- [ ] Cedar → IAM JSON translator implemented with the five unit tests from Section 2.5 passing (output
      pasted), including `s3:ListBuckets → s3:ListAllMyBuckets` and no-widening-to-`*` behavior
- [ ] `ValidatePolicy` and `CheckNoNewAccess` both called before every apply attempt; `ANALYZER_INVALID`
      implemented for both `VALIDATION_ERROR` and `NEW_ACCESS`, demonstrated with real output for cases
      (a)–(d) in Section 3
- [ ] Lambda execution role gained only the two `access-analyzer:*` actions — no IAM write permissions
- [ ] `--apply` and `--policy-name` implemented; every guard in 4.2 demonstrated refusing; a real run
      confirms declining (`N`) applies nothing, exits 0 and records `DECLINED`
- [ ] Real successful `PutRolePolicy` run against `cedar-sentinel-demo-role` overwriting the existing inline
      policy, with pasted `GetRolePolicy` read-back and post-apply `ListRolePolicies` /
      `ListAttachedRolePolicies` output; `previous_policy` snapshot shown in the results item
- [ ] Retry/backoff implemented for `ThrottlingException`; `MalformedPolicyDocumentException` and
      `LimitExceededException` reported clearly, not as stack traces; `APPLIED_UNVERIFIED` path implemented
- [ ] `scripts/reset_demo_role.py` implemented, refusing any other role; one real apply → reset → apply cycle
      pasted
- [ ] Persistent AVP audit store created with a registered schema, distinct from the disposable Phase 2 store;
      one real `CreatePolicy` call demonstrated firing only after a successful apply, with pasted `GetPolicy`
      output; evidence that `DECLINED` / `ANALYZER_INVALID` runs wrote nothing
- [ ] Dashboard: placeholder text replaced, and stretch goal either demonstrated with a real recorded run or
      explicitly and clearly deferred to Phase 4 in the response doc
- [ ] `docs/architecture.md`, `docs/limitations-and-mitigations.md`, `docs/ai-tool-disclosure.md` updated per
      Section 9
- [ ] Pre-push secret/PII scan run and reported (including `dashboard/run.json` and any pasted evidence)
- [ ] PR opened against `main` — **not merged**, no tag applied

---

## 11. Handoff note to Phase 4

Phase 4 (Sun, Sep 20) is video, writeup, and submission only — per the blueprint's risk table, features
freeze at the end of today regardless of how Section 8 lands. Nothing beyond bug fixes should be built after
this phase closes. The demo script from `docs/differentiators.md` — pre-seeded broad role, CLI trigger,
before/after diff, verified and applied — is now fully real end-to-end, not simulated, which is the whole
point of today's work. `scripts/reset_demo_role.py` exists so the demo can be re-recorded from a clean broad
state.

---

## Response

**Once this phase is complete, the agent's report goes in `responses/phase-03-response.md`, following the
same evidence standard as the last two fix rounds — every acceptance check needs pasted, real output, not a
description of what should happen. State explicitly which "Decision" defaults from Section 1 were used.**
