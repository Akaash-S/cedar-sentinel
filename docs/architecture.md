<!-- Intended repo path: docs/architecture.md -->
# Architecture Notes — Cedar Sentinel

This file does **not** duplicate the full architecture. The authoritative design lives in
`00-master-blueprint.md`. This file tracks anything discovered *during the build* that
deviates from, extends, or corrects the blueprint — dated, so the Day 4 writeup doesn't
require reconstructing your own reasoning from memory.

---

## Reference: core pipeline (as designed)

```
Python CLI → EventBridge → SQS → Lambda → CloudTrail Trail + CloudWatch Logs (baseline)
    → Bedrock (reasoning) → Cedar (verification via AVP) → IAM policy translation
    → dry-run approval → enforcement
```

See the master blueprint, Section 4, for the full diagram and Section 2 for why Cedar/AVP
is a **verification layer**, not a live AWS-call enforcement mechanism — IAM is the actual
enforcement point.

---

## CloudWatch Logs Insights query pattern

*(Fill in during Phase 1, Section 5 — record the exact scoped query validated, so Phase 2
can reuse the shape without re-deriving it. Starting point, matching the CloudTrail Lake
query this replaced — narrow to one `eventName`, short time window:)*

**Phase 1 validation query** (narrow, used to prove connectivity):
```
fields eventTime, eventName, eventSource, userIdentity.arn
| filter eventName = "AssumeRole"
| sort eventTime desc
| limit 20
```

**Phase 2 production query** (parameterized by role ARN, aggregated — this is what Lambda runs):
```
filter userIdentity.sessionContext.sessionIssuer.arn = "<ROLE_ARN>"
| stats count(*) as call_count by eventName
| sort call_count desc
| limit 200
```
`userIdentity.sessionContext.sessionIssuer.arn` is used (not `userIdentity.arn`) because
CloudTrail stores the assumed-role *session* ARN in the top-level field; the session issuer
field reliably contains the base role ARN regardless of session name.
Lookback window: 7 days. Result: `{eventName: count}` map handed to Bedrock.

---

## Phase 2 new components

*(These extend the original blueprint — not deviations, just additions.)*

| Date | Component | Description |
|---|---|---|
| 2026-09-18 | **DynamoDB table `cedar-sentinel-results`** | Async return path for the Lambda pipeline. CLI generates a UUID4 `request_id` when publishing an event; Lambda writes its full result here (observed-actions map, drafted Cedar policy, rationale, coverage verdict, Cedar validation verdict, and `stage_timings`). CLI polls `get_item` every 2 seconds, 30-second timeout. TTL: 72 hours. |
| 2026-09-18 | **Disposable AVP policy store** | A single throwaway Amazon Verified Permissions policy store (`cedar-sentinel-dev-validation`) used exclusively for Cedar schema registration (`PutSchema`, STRICT mode) and draft-policy validation (`CreatePolicy` → validate → `DeletePolicy`). Never the real persistent policy store. Store ID is stable across Lambda invocations (persisted in SSM). |
| 2026-09-18 | **SSM Parameter `/cedar-sentinel/dev/avp-policy-store-id`** | Holds the disposable AVP policy store ID between Lambda invocations so the store is reused rather than recreated on every cold start. Lambda role has `ssm:GetParameter` and `ssm:PutParameter` on the `/cedar-sentinel/*` path only. |
| 2026-09-18 | **`stage_timings` array on DynamoDB result item** | Four `{stage, start, end}` ISO timestamp pairs (one per pipeline stage: `cloudwatch_query`, `bedrock_call`, `coverage_check`, `cedar_validation`). Written as part of the single result `PutItem`. Phase 2 only captures these; Phase 3 dashboard uses them to replay each stage with real recorded durations. |

---

## Deviation log

*(Append an entry every time the actual build diverges from the blueprint.)*

| Date | What changed | Why |
|---|---|---|
| 2026-09-14 | Interception CLI language changed from Go to Python, adopted from Day 1 rather than kept as the Day-2 fallback | The task only requires reading `terraform show -json` output and extracting a policy — it never needed live interception of `terraform apply`. Go's advantages (static binary, concurrency) go unused since the CLI is invoked by hand, twice, per the confirmed demo script — while its costs (compiled build loop, thinner `verifiedpermissions` SDK coverage, more awkward nested-JSON parsing) bought nothing. Starting on the validated fallback path from Day 1 also removes the risk of losing a full day to the Go proxy before falling back anyway. |
| 2026-09-17 | Historical usage baseline changed from CloudTrail Lake to a standard CloudTrail Trail delivering to CloudWatch Logs, queried via CloudWatch Logs Insights | AWS closed CloudTrail Lake to new customers on May 31, 2026; attempting to create an event data store on this (new) account returned `InvalidParameterException: CloudTrail Lake is no longer accepting new customers`. Standard CloudTrail Trails are unaffected by the closure — it's a separate capability — and AWS explicitly directs new customers toward CloudWatch for equivalent functionality. CloudWatch Logs Insights charges the same $0.005/GB-scanned rate Lake did for queries, and at hackathon scale, ingestion and queries both stay within CloudWatch's 5 GB/month free tier. Nothing downstream of "Lambda queries a usage baseline" changes — only the API Lambda calls (`logs.start_query`/`get_query_results` instead of the CloudTrail Lake query API) and the query syntax (CloudWatch Logs Insights instead of SQL). |
| 2026-09-17 | Amplify app deleted and recreated as GitHub-connected from creation (new URL: https://main.d3i4xcsmv7sca9.amplifyapp.com) | Amplify app was initially created via manual CLI zip deploy for Day 1 verification. The existing app could not be converted to Git-connected hosting after the fact because Amplify Hosting does not support attaching a repository to an already-manually-deployed branch. Resolved by deleting the app and recreating it fresh, connected to GitHub from creation. Live URL changed as a result; see README for current URL. |
| 2026-09-17 | CLI IAM policy parser extended to handle `aws_iam_user_policy`, `aws_iam_group_policy`, and `aws_iam_role` inline definitions | Added defensive coverage in `cli/cedar_sentinel.py` beyond standard `aws_iam_role_policy` / `aws_iam_policy` to handle all standard Terraform IAM resource types cleanly. |
| 2026-09-17 | EventBridge rule configured with dual event sources (`cedar.sentinel.test` and `cedar.sentinel`) | Enables both Phase 1 test event routing and downstream Phase 2 production dispatches without requiring infrastructure SAM template updates. |
| 2026-09-18 | Cedar validation path changed from local Cedar CLI to disposable AVP policy store | Local Cedar CLI not available in the build environment. Per the fallback defined in `instructions/phase-02-core-logic.md` Section 6, Cedar formal verification uses a throwaway AVP policy store (`PutSchema` + `CreatePolicy` for validation + `DeletePolicy` cleanup). The verification outcome (pass/fail + messages) is identical to local CLI validation; only the mechanism differs. |
| 2026-09-18 | Bedrock reasoning handler updated to support resilient multi-model invocation | Bedrock Lambda handler defaults to the configured model (`BEDROCK_MODEL_ID`) and includes automatic fallback to `meta.llama3-70b-instruct-v1:0` if the primary model is unavailable. The fallback path now emits a loud CloudWatch log line `FALLBACK MODEL USED: <model-id>` so it can never be silently missed. |
| 2026-09-18 | Primary Bedrock model switched from Claude (Anthropic) to Amazon Nova Lite (`apac.amazon.nova-lite-v1:0`) | Anthropic models require an AWS Marketplace subscription for model access; payment verification failed repeatedly on this account (debit card, no credit card). Amazon Nova Lite is a first-party Amazon model — no Marketplace subscription required. The cross-region APAC inference profile (`apac.amazon.nova-lite-v1:0`) is used. Lambda IAM policy updated to list the profile ARN and all six APAC foundation-model ARNs it routes to; `aws-marketplace:*` removed from the execution role. Fallback chain unchanged (still Meta Llama 3 70B). |
| 2026-09-19 | CLI self-analysis guard added | Added a check in `cli/cedar_sentinel.py` that refuses to analyze a `--role-arn` that matches Cedar Sentinel's own Lambda execution role ARN (read from the `LAMBDA_EXECUTION_ROLE_ARN` env var, injected by SAM from `!GetAtt LambdaExecutionRole.Arn`). Proceeding would analyze the tool's own AWS calls, not a real workload's. The `--allow-self-analysis` flag bypasses the guard for controlled testing. |
| 2026-09-19 | CloudWatch Insights query extended to capture `eventSource`; action labels now prefixed with service name | Previous query aggregated only by `eventName` (e.g. `GetParameter`), causing the Bedrock reasoning stage to produce mislabeled Cedar actions (`ssm:PutSchema` instead of `verifiedpermissions:PutSchema`). Query now groups by `eventName, eventSource`; the parse step strips `.amazonaws.com` to derive the service prefix and emits `service:EventName` keys (e.g. `verifiedpermissions:PutSchema`). No schema or API changes — only the CloudWatch Insights query string and the parse loop changed. |
| 2026-09-19 | Distinct `CEDAR_INVALID` status added for Cedar validation failures | Previously, failed Cedar formal verification (AVP schema/syntax rejection) was written to DynamoDB as `status: COMPLETE` because `write_result` did not branch on `cedar_result['passed']`. Status is now explicitly set to `CEDAR_INVALID` on verification failure, writing the validation error messages and offending policy text. The CLI displays `[FAIL] Cedar formal verification rejected the draft policy` and exits with non-zero code. |
| 2026-09-19 | Bedrock reasoning prompt updated for zero-observed-actions case | In cases with zero observed CloudTrail activity for a principal, the model previously drafted free-text `deny all;` which failed AVP syntax validation. System prompt updated with explicit rule and few-shot example requiring valid Cedar syntax (`forbid(principal, action in [CedarSentinel::Action::"none"], resource);`) when no actions are observed. |
| 2026-09-19 | Bedrock model ID resolution logged before invocation | Added `logger.info("Resolved BEDROCK_MODEL_ID: %s", model_id)` at the start of `stage_bedrock_call` to ensure the deployed model ID is immediately visible in CloudWatch logs prior to invoking Bedrock. |

