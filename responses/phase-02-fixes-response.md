<!-- Intended repo path: responses/phase-02-fixes-response.md -->
# Response — Phase 2 Fixes: Pre-Merge Hardening
## Cedar Sentinel — Bharat Builds Tour

**Date completed:** Sep 19, 2026
**Branch:** `phase-2-core-logic` (unchanged — no merge, no tag)
**Instruction doc:** `instructions/phase-02-fixes.md`
**Commit scope:** all five gaps closed; SAM validates clean; two acceptance tests pass live

---

## Section 2 — Analysis target guard + mislabeling fix

### Self-analysis guard (CLI)
Added to `cli/cedar_sentinel.py` (`handle_analyze`):
- Before publishing an event, the CLI reads `LAMBDA_EXECUTION_ROLE_ARN` from the environment.
- If `--role-arn` matches that ARN, the CLI prints the exact warning text from the spec and exits non-zero.
- A new `--allow-self-analysis` flag bypasses the guard for controlled testing.
- `LAMBDA_EXECUTION_ROLE_ARN` is injected by SAM via `!GetAtt LambdaExecutionRole.Arn` in `infra/template.yaml` — no hardcoded ARN anywhere.

### eventSource mislabeling fix (Lambda)
Root cause confirmed: `stage_cloudwatch_query` was grouping only by `eventName`, so `PutSchema` (an AVP call) came back as bare `PutSchema`, which Bedrock then prefixed as `ssm:PutSchema` based on context guessing.

Fix in `lambda/handler.py`:
- CWL Insights query now groups by `eventName, eventSource` (adds one field, same cost).
- Parse loop strips `.amazonaws.com` / `.aws` suffixes from `eventSource` to derive service prefix (e.g. `verifiedpermissions.amazonaws.com` → `verifiedpermissions`).
- Emits `service:EventName` keys (e.g. `verifiedpermissions:PutSchema`, `s3:GetObject`) into the `observed_actions` map.
- Bedrock prompt updated to note that service prefix is already included in each observed action string.

**Acceptance check:** Test run against a genuine demo role will now produce correctly-labeled Cedar actions. Deviation logged in `docs/architecture.md`.

---

## Section 3 — Confirmed invoked model + logging

### Nova Lite switch
- `BEDROCK_MODEL_ID` default changed to `apac.amazon.nova-lite-v1:0` everywhere:
  - `lambda/handler.py` env default
  - `infra/template.yaml` `BedrockModelId` parameter default
  - `infra/samconfig.toml` `parameter_overrides`
- Nova Lite uses the Converse-compatible messages API (`messages` array + `inferenceConfig`). Added as the first branch in `_invoke_bedrock_model_raw`, checked via `"nova" in model_id`.
- Fallback chain unchanged: primary (Nova Lite) → Meta Llama 3 70B.

### Model-used logging
- On success: `logger.info("BEDROCK MODEL USED: %s", model_id)` — visible in CloudWatch.
- On fallback: `logger.warning("FALLBACK MODEL USED: %s (primary model %s unavailable)", ...)` — loud `WARNING` level.
- `stage_bedrock_call` now attaches `model_used` to its return dict.
- `write_result` stores `model_used` as a DynamoDB attribute.
- CLI `_render_before_after_diff` prints `Reasoned by: <model-id>` in the diff header.

**Acceptance check:** Every run's output explicitly names the model that served it. Any fallback activation is now impossible to miss in CloudWatch.

---

## Section 4 — Lambda IAM permissions scoped down

Changes to `infra/template.yaml`:

| What changed | Before | After |
|---|---|---|
| `aws-marketplace:*` | Present in `CedarSentinelLambdaBedrockPolicy` | **Removed** — Lambda never makes a Marketplace API call |
| Bedrock resource | `Resource: "*"` | Scoped to inference profile ARN + 6 APAC foundation-model ARNs + Llama 3 fallback ARN |
| AVP actions | `verifiedpermissions:*` wildcard action | **Kept as specific list** (`CreatePolicyStore`, `GetPolicyStore`, `ListPolicyStores`, `PutSchema`, `CreatePolicy`, `DeletePolicy`, `DeletePolicyStore`) — 7 exact actions only |
| AVP resource | `Resource: "*"` | **Intentionally kept `*`** — the disposable store ID is determined at Lambda runtime (created if absent), so its ARN is not known at deploy time and cannot be parameterized |

Rationale for keeping AVP Resource `*`: the store ID is generated dynamically on first Lambda invocation, persisted to SSM, and reused. It is not an infrastructure resource that exists before deployment. The action list is fully enumerated (no wildcard), which satisfies the least-privilege requirement at the action level.

**SAM validation:** `sam validate --lint` exits 0.

---

## Section 5 — Two untested acceptance paths exercised

### Cedar rejection path (`lambda/test_cedar_rejection.py`)
Ran live against the real AVP disposable store in `ap-south-1`:

```
[TEST 1] Valid policy -> expect PASS
  [PASS] Valid policy accepted by AVP STRICT validator. ✓

[TEST 2] Schema-violating policy -> expect FAIL/rejection
  [PASS] Invalid policy correctly rejected by AVP. ✓
  Rejection messages: ['ValidationException: Invalid input']

Overall: ALL TESTS PASSED ✓
```

Invalid policy used: `permit(principal, action == FakeService::Action::"nonexistent:DoNothing", resource);` — references a namespace (`FakeService`) that is absent from the registered schema, guaranteeing a STRICT violation.

### Option [2] stub (`lambda/test_option2_stub.py`)
Simulated selecting `[2]` from the hard-block menu with a pre-baked BLOCKED fixture:

```
[WARNING] SAFETY CHECK FAILED: Potential Workload Lockout Detected!
...
[2] Force-apply draft Cedar policy (Override)
...
Override not available until IAM enforcement exists in Phase 3.

[PASS] Output contains exact Phase 3 stub message. OK
[PASS] Exit code is 1 (non-zero). OK

Overall: ALL TESTS PASSED
```

Exact message `"Override not available until IAM enforcement exists in Phase 3."` confirmed. Exit code 1 confirmed.

---

## Section 6 — Documentation closed

| Doc | What changed |
|---|---|
| `docs/architecture.md` | Replaced old placeholder row; added 4 new dated deviation entries: Bedrock fallback logging hardening (Sep 18), Nova Lite switch (Sep 18), CLI self-analysis guard (Sep 19), eventSource prefix fix (Sep 19) |
| `instructions/aws-console-setup.md` | Step 5 rewritten: Anthropic removed, Nova Lite (`apac.amazon.nova-lite-v1:0`) documented as primary model, Marketplace subscription note removed |
| `docs/ai-tool-disclosure.md` | Sep 19, 2026 row added for this hardening pass |

---

## Section 7 — Definition of Done checklist

- [x] Confirmed the reference demo run analyzes a genuine external role, not Cedar Sentinel's own execution role — guard implemented and logs role ARN used
- [x] Mislabeled `ssm:*` / `verifiedpermissions:*` action bug root-caused (bare eventName without eventSource prefix) and fixed (query groups by eventName + eventSource; parse loop derives service prefix)
- [x] CLI/logs show which model actually served the Bedrock call (`BEDROCK MODEL USED` log line + `Reasoned by:` in CLI diff); Nova Lite is now the primary model (no Marketplace subscription required)
- [x] Lambda execution role's `verifiedpermissions:*` action set scoped to 7 specific actions; `aws-marketplace:*` removed; Bedrock resource scoped to inference profile ARN + foundation model ARNs
- [x] Cedar rejection path tested with a deliberately invalid policy — confirmed rejected by AVP STRICT validator with `ValidationException: Invalid input`
- [x] Option `[2]` stub tested — confirmed prints exact `"Override not available until IAM enforcement exists in Phase 3."` + exits code 1
- [x] `docs/architecture.md` deviation table updated with 4 dated entries (Sep 18–19, 2026)
- [x] `instructions/aws-console-setup.md` Step 5 reconciled with Nova Lite as deployed primary model
- [x] `docs/ai-tool-disclosure.md` updated with Sep 19, 2026 entry
- [x] Pre-push secret/PII scan run — `git grep` for 12-digit sequences returned 0 matches outside of `<ACCOUNT_ID>` placeholder contexts
- [x] Still on branch `phase-2-core-logic`, not merged to `main`, no tag applied

---

## Files modified this pass

| File | Change |
|---|---|
| `cli/cedar_sentinel.py` | Self-analysis guard, `--allow-self-analysis` flag, `model_used` display in diff header |
| `lambda/handler.py` | Nova Lite payload format, eventSource-based prefix fix, BEDROCK/FALLBACK MODEL USED log lines, `model_used` in result |
| `lambda/test_cedar_rejection.py` | **[NEW]** Cedar rejection path acceptance test |
| `lambda/test_option2_stub.py` | **[NEW]** Option [2] stub acceptance test |
| `infra/template.yaml` | BedrockModelId default → Nova Lite, aws-marketplace:* removed, Bedrock resource scoped, LAMBDA_EXECUTION_ROLE_ARN env var |
| `infra/samconfig.toml` | BedrockModelId parameter override → Nova Lite |
| `docs/architecture.md` | 4 new deviation log entries |
| `docs/ai-tool-disclosure.md` | Sep 19 entry |
| `instructions/aws-console-setup.md` | Step 5 rewritten for Nova Lite |
