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

```
fields eventTime, eventName, eventSource, userIdentity.arn
| filter eventName = "AssumeRole"
| sort eventTime desc
| limit 20
```

---

## Deviation log

*(Append an entry every time the actual build diverges from the blueprint.)*

| Date | What changed | Why |
|---|---|---|
| 2026-09-14 | Interception CLI language changed from Go to Python, adopted from Day 1 rather than kept as the Day-2 fallback | The task only requires reading `terraform show -json` output and extracting a policy — it never needed live interception of `terraform apply`. Go's advantages (static binary, concurrency) go unused since the CLI is invoked by hand, twice, per the confirmed demo script — while its costs (compiled build loop, thinner `verifiedpermissions` SDK coverage, more awkward nested-JSON parsing) bought nothing. Starting on the validated fallback path from Day 1 also removes the risk of losing a full day to the Go proxy before falling back anyway. |
| 2026-09-17 | Historical usage baseline changed from CloudTrail Lake to a standard CloudTrail Trail delivering to CloudWatch Logs, queried via CloudWatch Logs Insights | AWS closed CloudTrail Lake to new customers on May 31, 2026; attempting to create an event data store on this (new) account returned `InvalidParameterException: CloudTrail Lake is no longer accepting new customers`. Standard CloudTrail Trails are unaffected by the closure — it's a separate capability — and AWS explicitly directs new customers toward CloudWatch for equivalent functionality. CloudWatch Logs Insights charges the same $0.005/GB-scanned rate Lake did for queries, and at hackathon scale, ingestion and queries both stay within CloudWatch's 5 GB/month free tier. Nothing downstream of "Lambda queries a usage baseline" changes — only the API Lambda calls (`logs.start_query`/`get_query_results` instead of the CloudTrail Lake query API) and the query syntax (CloudWatch Logs Insights instead of SQL). |
| 2026-09-17 | Amplify deployed via manual CLI zip upload for the initial Day 1 verification; switched to GitHub-connected auto-deploy after Phase 1 merge | Browser-based GitHub OAuth authorization is required to establish Git-connected CI/CD in the AWS Amplify console; manual zip artifact deployment via CLI verified the live HTTPS endpoint during Day 1 scaffolding as a resolved transitional step. |
| 2026-09-17 | CLI IAM policy parser extended to handle `aws_iam_user_policy`, `aws_iam_group_policy`, and `aws_iam_role` inline definitions | Added defensive coverage in `cli/cedar_sentinel.py` beyond standard `aws_iam_role_policy` / `aws_iam_policy` to handle all standard Terraform IAM resource types cleanly. |
| 2026-09-17 | EventBridge rule configured with dual event sources (`cedar.sentinel.test` and `cedar.sentinel`) | Enables both Phase 1 test event routing and downstream Phase 2 production dispatches without requiring infrastructure SAM template updates. |
| — | — | — |
