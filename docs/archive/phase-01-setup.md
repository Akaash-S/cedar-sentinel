# Instruction Document 1 — Phase 1: Setup
## Cedar Sentinel — First Commit (Bharat Builds Tour)

**To:** Antigravity coding agent
**From:** Project owner, via `00-master-blueprint.md`
**Event day this maps to:** Thursday, Sep 17, 2026 — Kickoff
**Branch:** `phase-1-setup` (off `main`)
**Tag on completion:** `v0.1-setup`
**Response goes to:** `responses/phase-01-response.md`

**Revision note (Sep 14, 2026):** This document previously specified a Go CLI proxy
intercepting `terraform apply` live. That's replaced below with a Python CLI reading
the JSON output of `terraform plan` — the blueprint's own Day-2 fallback path, adopted
from Day 1 instead of built toward. See `docs/architecture.md`'s deviation log for the
reasoning. Nothing downstream of "an EventBridge event exists" changes.

**Revision note (Sep 17, 2026 — kickoff day):** Section 5 previously used CloudTrail
Lake for the historical usage query. AWS closed CloudTrail Lake to new customers on May
31, 2026, and this account cannot create an event data store as a result. Section 5 now
uses a standard CloudTrail Trail delivering to CloudWatch Logs, queried via CloudWatch
Logs Insights — the equivalent capability. See `docs/architecture.md`'s deviation log.

---

## 0. Objective & Scope

Today's job is **scaffolding only**. By the end of this phase, we have a repository that runs, deploys, and proves each data source is reachable — but contains **zero product logic**.

**Explicitly out of scope for Phase 1 — do not build these yet, even partially:**
- No policy-diff or drift-detection logic in the CLI
- No Bedrock prompt, no reasoning code
- No Cedar policy generation or Verified Permissions calls
- No IAM translation/enforcement logic
- No dashboard UI beyond a placeholder page

If you find yourself writing logic that decides *what a policy should say*, stop — that's Phase 2. Phase 1 only proves the pipes are connected.

**Definition of "done" in one sentence:** every AWS service we plan to use responds successfully to a trivial, hardcoded test call, from code that lives in a properly structured, version-controlled repo.

---

## 1. Pre-flight Checklist (human confirms before agent proceeds)

- [x] AWS Builder Center profile exists, student verification shows **complete**
- [x] Bedrock → Model access enabled for a current-generation Claude model, region: `ap-south-1`, model ID: `anthropic.claude-sonnet-4-6`
- [x] CloudTrail Trail created and logging, CloudWatch Logs group receiving events, region: `ap-south-1`
- [x] Dedicated project IAM user/role exists (not root/admin), credentials available locally
- [x] `aws sts get-caller-identity` returns the expected account
- [x] AWS Budget alert set ($15–20 threshold)
- [x] Empty GitHub repository created
- [x] Target AWS region decided and will be used consistently: `ap-south-1`
- [x] Terraform installed locally, `terraform init` runs cleanly against a placeholder config

**Agent: confirm every box above with the human before proceeding if any are unclear.**

---

## 2. Repository Scaffold

```
cedar-sentinel/
├── cli/
├── lambda/
├── infra/
├── dashboard/
├── docs/
│   ├── architecture.md
│   ├── ai-tool-disclosure.md
│   └── attribution.md
├── .gitignore
├── LICENSE
└── README.md
```

1. Initialize git, create `phase-1-setup` branch off an empty `main`.
2. `.gitignore`: exclude `.env`, `*.pyc`, `__pycache__/`, `.aws-sam/`, `.venv/`, `*.tfstate*`, `node_modules/`, any `.pem`/credential files.
3. `LICENSE`: MIT unless the project owner specifies otherwise.
4. `README.md`: project name, one-paragraph description, track (Ship It), "Status: Phase 1 — Setup" line, updated each phase.
5. Copy the seed files from this planning set into `docs/` (already drafted — see `docs/architecture.md`, `docs/ai-tool-disclosure.md`, `docs/attribution.md`) rather than generating fresh versions.

---

## 3. Python CLI Skeleton

The CLI's only job is: read a Terraform plan's JSON output, pull out the IAM policy a
role is being granted, and publish that as an event. It does not intercept `terraform
apply` in flight — it reads a file Terraform already produces.

1. `cd cli && python3 -m venv .venv && source .venv/bin/activate`
2. `pip install boto3` — that's the only dependency needed for Phase 1. Don't add a CLI framework (Click, Typer) until Phase 2 shows it's actually needed; use the standard library `argparse` for now.
3. Build a minimal CLI, e.g. `cli/cedar_sentinel.py`:
   - `python cedar_sentinel.py check-aws` → calls `sts:GetCallerIdentity`, prints the account ID
   - `python cedar_sentinel.py analyze --plan-file <path>` → loads the Terraform plan JSON, walks `resource_changes`, extracts any `aws_iam_role_policy` / `aws_iam_policy` resource's policy document
4. `requirements.txt` pins `boto3` (and nothing else yet).

**How the input file gets produced (document this in the README, it's a two-command habit, not automation to build):**
```bash
terraform plan -out=tfplan.binary
terraform show -json tfplan.binary > tfplan.json
```

**Acceptance check:** `python cedar_sentinel.py check-aws` prints your real AWS account ID. `python cedar_sentinel.py analyze --plan-file tfplan.json` against a sample plan (a single `aws_iam_role_policy` resource is enough) correctly prints the policy document it found.

---

## 4. AWS Infrastructure (IaC, not console click-ops)

1. `infra/template.yaml` (SAM): one EventBridge bus, one SQS queue subscribed via a rule (placeholder pattern `source: "cedar.sentinel.test"`), one Lambda (Python 3.12) that logs the SQS message body, and an IAM execution role scoped to exactly `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on that one queue plus basic CloudWatch Logs writes.
2. `sam build && sam deploy --guided`; save `infra/samconfig.toml` (gitignore anything with secrets).
3. **Acceptance check:** run `python cedar_sentinel.py analyze --plan-file tfplan.json` against a sample plan, confirm the resulting event reaches the Lambda's CloudWatch log via EventBridge → SQS.

---

## 5. CloudTrail Trail + CloudWatch Logs — Scoped Test Query

CloudTrail Lake is closed to new customers as of May 31, 2026. This step uses a standard
CloudTrail Trail delivering management events to CloudWatch Logs instead — the
equivalent capability, unaffected by the closure.

1. Console → **CloudTrail → Trails → Create trail**. Name it (e.g. `cedar-sentinel-trail`), point it at a new or existing S3 bucket, and enable **CloudWatch Logs** delivery in the same wizard — let it auto-create the log group and the IAM role CloudTrail needs (name the role to match the `cedar-sentinel-*` pattern if creating it by hand instead, so it's covered by the dev user's IAM policy).
2. Under event types, select **Management events** only — data and network activity events add cost this project doesn't need.
3. Confirm **Logging: On**, and confirm events are actually landing in the new CloudWatch Logs group (allow a few minutes for first delivery).
4. Run one scoped test query in **CloudWatch → Logs → Logs Insights**: a specific `eventName` (e.g. `AssumeRole`), short time window (last 24h). Example:
   ```
   fields eventTime, eventName, eventSource, userIdentity.arn
   | filter eventName = "AssumeRole"
   | sort eventTime desc
   | limit 20
   ```
5. Save the exact query text into `docs/architecture.md` under "CloudWatch Logs Insights query pattern."

**Acceptance check:** query returns without error; note the GB-scanned cost so scope discipline starts now (should be well within the 5 GB/month free tier at this volume).

---

## 6. Config & Secrets Handling

1. `infra/.env.example` (committed): `AWS_REGION=`, `BEDROCK_MODEL_ID=`, `CLOUDWATCH_LOG_GROUP_NAME=`, placeholder values only.
2. `.env` locally (gitignored) with real values.
3. Review `git diff` before every commit this phase — no real credentials, ARNs, or account IDs.

---

## 7. Dashboard Placeholder

1. `dashboard/index.html`: static page reading "Cedar Sentinel — dry-run dashboard coming in Phase 3."
2. Connect to Amplify Hosting (console, one-time) so a real URL exists from Day 1.
3. **Acceptance check:** the Amplify URL loads the placeholder page.

---

## 8. Definition of Done — Phase 1 Acceptance Criteria

- [ ] Repo structure matches Section 2, pushed with real Sep 17 commit timestamps
- [ ] `cedar_sentinel.py check-aws` prints the correct AWS account ID
- [ ] `cedar_sentinel.py analyze --plan-file <sample>` correctly extracts a test IAM policy
- [ ] SAM stack deploys; test event flows EventBridge → SQS → Lambda → CloudWatch Logs
- [ ] Lambda execution role scoped (verified in IAM console)
- [ ] CloudTrail Trail is logging; CloudWatch Logs Insights test query succeeds; pattern documented
- [ ] Amplify Hosting URL live, serves placeholder
- [ ] `docs/ai-tool-disclosure.md` and `docs/attribution.md` present with initial entries
- [ ] No secrets/ARNs/account IDs in git history
- [ ] PR `phase-1-setup` → `main` opened, reviewed, squash-merged
- [ ] `main` tagged `v0.1-setup`

---

## 9. Handoff Note to Phase 2

Phase 2 (Fri, Sep 18) builds the reasoning pipeline: CloudWatch Logs Insights baseline → Bedrock → Cedar/Verified Permissions.

**No Go/Python checkpoint is needed this time** — Phase 1 starts directly on the path the
original blueprint validated as a safe fallback, so there's nothing to swap mid-build.
The demo itself (per `docs/differentiators.md`) was always going to trigger the CLI by
hand, twice, to show drift detection — not run as an always-on daemon — so this CLI is
already built to match how it'll actually be used in the video.

**Lambda's baseline query changes API, not shape:** Phase 2 code should call
`boto3`'s `logs.start_query()` / `logs.get_query_results()` against the CloudWatch Logs
group from Section 5, rather than a CloudTrail Lake query. The rest of the reasoning
pipeline (Bedrock prompt, Cedar verification) is unaffected — it only ever needed a list
of observed actions and call counts, regardless of which AWS API produced them.

---

## Response

**Once this phase is complete, the agent's report goes in `responses/phase-01-response.md`,
using the template already created there — do not write the response inline here.**
