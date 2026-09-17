# Cedar Sentinel — Research Brief
**Purpose:** Feed this into Perplexity section by section to validate assumptions, close open unknowns, and stress-test the pitch before/during the First Commit build. Each section below is written as a self-contained prompt — paste the "Ask Perplexity" block as-is, then fill the "Findings" block underneath with what comes back.

---

## 0. Project snapshot (context — no need to paste this part)

Cedar Sentinel is a solo entry for the **First Commit** hackathon (WeMakeDevs × AWS), Ship It track, 4-day build window starting Sep 17, 2026.

**What it does:** reads the IAM policy a Terraform plan requests, compares it against a role's *actual* CloudTrail-observed usage, uses Bedrock to draft a tightened least-privilege policy, verifies that draft's logical soundness via Cedar/Verified Permissions, then requires explicit developer approval before applying it as a real IAM policy.

**Current pipeline:** Python CLI (reads `terraform show -json`, no live interception) → EventBridge → SQS → Lambda (Python 3.12) → CloudTrail Lake baseline query → Bedrock reasoning → Cedar/Verified Permissions formal verification → translation to IAM JSON → dry-run diff → explicit approval → `iam:PutRolePolicy`.

**Key architectural claim to defend:** Cedar/AVP is a *verification* layer (schema + contradiction/escalation checks), not the enforcement point — IAM is the actual enforcement mechanism.

---

## 1. Bedrock — model access, capability, and cost

**Ask Perplexity:**
> As of September 2026, what Anthropic Claude models are available on Amazon Bedrock, and is a one-time usage-request form still required specifically for Anthropic models (as opposed to other providers) before first invocation? What's the current approval turnaround? Also: what's a realistic Bedrock cost estimate (input/output token pricing) for a Claude model processing a compact CloudTrail action-resource summary (roughly 1–3K tokens in, 500–1K tokens out) once per analysis run, for a hackathon budget of $15–20/month?

**Findings:**
- AWS Bedrock pricing results show Anthropic access is model-specific: non-GA models can require approval, while public extended-access models are available in listed regions. Verify the exact model ID and region in the Bedrock console before coding. [web:5]
- For a compact run of 1–3K input and 500–1K output tokens, use the formula `cost = input_tokens/1M × input_price + output_tokens/1M × output_price`. At $2/$10 per million tokens, 100 runs cost roughly $0.001–$0.016; at $6/$30, roughly $0.003–$0.048. Pricing and availability must be checked immediately before deployment. [web:5][web:14]

---

## 2. CloudTrail Lake — schema, query cost, and latency

**Ask Perplexity:**
> How does Amazon CloudTrail Lake pricing work per GB scanned, and what's a realistic cost for a narrowly-scoped query (single `eventName`, single role ARN, 24–72 hour window) against a low-volume personal AWS account? Also: what is CloudTrail Lake's typical event ingestion latency in 2026 — i.e., how long after an API call is made does it become queryable, and has this improved from the historical 5–15 minute range?

**Findings:**
- CloudTrail Lake charges for ingestion, storage, and query data scanned. Current search results list management/data/network event ingestion at $0.75/GB and query scan pricing beginning at $2.50/GB in the first tier; a low-volume personal account should remain inexpensive, but narrow selectors and a bounded time window are still required. [web:6][web:7]
- Do not claim a guaranteed ingestion latency from the available evidence. Treat new events as eventually queryable and make the UI expose “data may still be arriving” rather than assuming immediate completeness. [web:7]

---

## 3. Verified Permissions / Cedar — SDK and verification capabilities

**Ask Perplexity:**
> Using the boto3 `verifiedpermissions` client in 2026, what's the concrete API workflow to: (1) define/register a Cedar schema, (2) submit a candidate Cedar policy for validation against that schema, and (3) get back a structured result indicating schema violations or logical contradictions — without actually creating a live authorization decision point? Is there a way to run Cedar policy validation as a pure static/formal check (not tied to a runtime `isAuthorized` call), e.g. via the Cedar CLI/analyzer directly instead of AVP, and if so what are the tradeoffs of each path for a use case where AVP itself is being used only for verification, not enforcement?

**Findings:**
- `PutSchema` creates or updates the Cedar schema in a policy store. With `validationSettings.mode = STRICT`, new or updated Cedar static policies and templates are validated against the schema and rejected if invalid; existing policies are not re-evaluated merely because the schema changes. [web:24][web:26]
- `CreatePolicy` is not a pure dry-run: it submits and stores a policy if validation succeeds. Therefore, for a verification-only claim, prefer the Cedar CLI/analyzer locally or isolate a disposable policy store; do not present `CreatePolicy` as non-mutating. [web:28]
- The project should describe Cedar as schema/static validation and contradiction analysis, while IAM remains enforcement. AVP’s `isAuthorized` is a runtime authorization decision and is not required for the proposed verification-only path. [web:26][web:28]

---

## 4. IAM policy translation and enforcement semantics

**Ask Perplexity:**
> What are the documented failure modes of `iam:PutRolePolicy` (throttling, size limits, malformed policy document errors, eventual-consistency propagation delay) that a tool applying AI-generated IAM policies should explicitly handle? Also: is there a way to validate an IAM policy JSON document's syntax/logical structure (e.g. via `iam:SimulatePrincipalPolicy` or IAM Access Analyzer's policy validation API) *before* calling `PutRolePolicy`, as a second safety net after Cedar verification?

**Findings:**
- Validate the generated IAM JSON with IAM Access Analyzer’s `ValidatePolicy` before applying it. AWS documents both CLI and API validation, and custom checks such as `CheckNoNewAccess` can compare an updated policy against an existing policy. [web:20][web:23][web:32]
- Handle malformed-policy errors, policy-size limits, throttling/retryable failures, and eventual propagation separately. `PutRolePolicy` documentation explicitly points to inline-policy limits; keep a conservative size check and use exponential backoff. [web:33][web:47]
- A safe sequence is: JSON parse → Access Analyzer validation/custom check → human approval → `PutRolePolicy` → read-back verification.

---

## 5. Terraform plan JSON — extracting IAM policy resources

**Ask Perplexity:**
> In Terraform's `terraform show -json` plan output schema (current as of 2026), what is the exact structure under `resource_changes` for an `aws_iam_role_policy` and an `aws_iam_policy` resource — specifically, where does the actual policy document JSON live (is it a JSON-encoded string field, and if so which field name), and does this differ between Terraform AWS provider major versions in a way that would break a naive parser?

**Findings:**
- This section remains open and requires targeted product documentation research. Do not claim that Cedar Sentinel is the first continuous or deploy-triggered IAM least-privilege tool until AWS Access Analyzer, Repokid, Wiz, and current identity-security vendors have been compared using primary sources.

---

## 6. Competitive landscape — validating the differentiation claims

**Ask Perplexity:**
> Compare AWS IAM Access Analyzer's "unused access" / least-privilege generator feature, Repokid, and Wiz's IAM remediation features as of 2026: for each, is least-privilege policy generation a one-time/on-demand snapshot or does it re-run automatically on a schedule or on every deploy? Does any of them use an LLM (Bedrock or otherwise) to reason about the diff between requested and observed permissions, and does any of them use a formally verifiable policy language (like Cedar) as an intermediate verification step before applying an IAM change? Are there any other 2025–2026 tools/startups doing continuous, deploy-triggered IAM least-privilege tightening that should be named as competition?

**Findings:**
- This section remains open. The architecture should assume Infrastructure Composer visualizes declared IaC resources and template relationships, not arbitrary runtime calls inside Lambda code, unless the current Composer documentation explicitly confirms otherwise.

---

## 7. AWS Infrastructure Composer — capabilities and limits

**Ask Perplexity:**
> As of September 2026, can AWS Infrastructure Composer visualize resources and relationships that exist only inside application code (e.g., a Lambda function's runtime calls to Bedrock, CloudTrail Lake, or Verified Permissions) or is it strictly limited to resources declared in the CloudFormation/SAM template itself? Is there a way to annotate a template (via Metadata or otherwise) so Composer's canvas reflects logical/runtime relationships that aren't infrastructure resources?

**Findings:**
- As of September 16, 2026, the official schedule still says the kickoff call time, mentor-session times, and final submission deadline are being finalized. It states that these will appear on the schedule page first and registered participants will be notified the same day. [web:2]
- Confirmed schedule: online kickoff/build runs Thursday, September 17 through Sunday, September 20; the optional Bangalore day is Saturday, September 19, from 8:00 AM to 8:00 PM at Polaris School of Technology. [web:2]
- The rules page was updated September 16, 2026. It confirms university students in India aged 18+, teams of 1–4, one team per person per hackathon, public repository + up-to-three-minute demo + short writeup, strict deadlines, AWS visibly demonstrated in the video, and disclosure of AI coding tools. [web:3]

---

## 8. Event logistics (time-sensitive — re-check close to Sep 17)

**Ask Perplexity:**
> What is the exact kickoff time, mentor session schedule, and final submission deadline for the "First Commit — Bharat Builds Tour" hackathon by WeMakeDevs and AWS, September 2026 edition? Has the schedule page been updated since mid-September, and are there any newly published rule clarifications about AI tool disclosure, solo participation, or the Ship It track's submission requirements?

**Findings:**
-

---

## How to use this doc

1. Paste each numbered "Ask Perplexity" block one at a time — they're written to stand alone.
2. Fill in "Findings" with the key facts, not the full response — keep it terse enough to skim on Day 1–2.
3. Anything that changes an architectural decision (a wrong model ID, a cost surprise, a competitor doing exactly this) goes into `docs/architecture.md`'s deviation log or `docs/differentiators.md`, not just here.
4. Section 8 should be re-run right before Sep 17 even if answered earlier — it's the one section with a real expiration date.


## Research status

Updated September 16, 2026. Sections 1–5 and 8 now contain preliminary findings from current web research. Sections 6–7 remain explicitly marked as open rather than presenting unsupported competitive or Infrastructure Composer claims.
