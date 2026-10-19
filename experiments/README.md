# Cedar Sentinel — Experiments & Verification Suite

This directory contains empirical experiment scripts and sanitized results validating the Cedar Sentinel least-privilege IAM analysis and enforcement pipeline across 5 diverse IAM plans and 50 live executions on AWS (`ap-south-1`).

---

## 1. Pipeline Architecture Diagram

```
                 Terraform Plan JSON (terraform show -json)
                                   │
                                   ▼
                              Python CLI
                                   │
                     (EventBridge: cedar.sentinel)
                                   │
                                   ▼
                          Amazon SQS Queue
                                   │
                                   ▼
                   AWS Lambda Pipeline Processor (Python 3.12)
 ┌─────────────────────────────────┴─────────────────────────────────┐
 │                                                                   │
 │  Stage 1: CloudWatch Logs Insights (Historical Usage Query)       │
 │  Stage 2: Amazon Bedrock (Nova Lite Reasoning & Cedar Draft)      │
 │  Stage 3: Deterministic Coverage Check (Lockout Safeguard)        │
 │  Stage 4: Amazon Verified Permissions (Cedar STRICT Schema Check) │
 │  Stage 5: Cedar → IAM JSON Translation & Action Normalization    │
 │  Stage 6: AWS IAM Access Analyzer (ValidatePolicy + CheckNoNewAccess)
 │                                                                   │
 └─────────────────────────────────┬─────────────────────────────────┘
                                   ▼
                      Amazon DynamoDB Results Table
                                   │
                                   ▼
                      CLI Interactive Diff & Approval
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         │                                                   │
  [N] Decline                                         [y] Approve
         │                                                   │
         ▼                                                   ▼
Status: DECLINED                                1. Snapshot previous_policy
(zero IAM changes)                              2. iam:PutRolePolicy
                                                3. Read-back verification
                                                4. Record in persistent AVP store
                                                5. Status: APPLIED
```

---

## 2. The 5 Distinct Test IAM Roles & Plans

| Plan ID | Role / Workload Name | Baseline Statements | Baseline Actions | Baseline Wildcards | Observed Telemetry |
|---|---|---|---|---|---|
| `plan_1_s3_ingest` | S3 Data Ingestion Pipeline | 1 statement | 1 (`s3:*`) | 1 wildcard | `s3:GetObject` (25), `s3:PutObject` (15), `s3:ListBucket` (8) |
| `plan_2_microservice` | DynamoDB & SQS Microservice | 2 statements | 2 (`dynamodb:*`, `sqs:*`) | 2 wildcards | `dynamodb:GetItem` (40), `dynamodb:PutItem` (30), `sqs:ReceiveMessage` (25), `sqs:DeleteMessage` (25) |
| `plan_3_monitoring` | CloudWatch Logs & Metrics Daemon | 2 statements | 3 (`logs:*`, `cloudwatch:*`, `PutMetricData`) | 2 wildcards | `logs:CreateLogStream` (4), `logs:PutLogEvents` (50), `cloudwatch:PutMetricData` (30) |
| `plan_4_analytics_overpermissive` | Over-Permissive Analytics Role | 4 statements (`s3`, `kinesis`, `sns`, `glue`) | 6 actions | 4 wildcards | `s3:GetObject` (18), `s3:PutObject` (10) (0 calls to Kinesis, SNS, Glue) |
| `plan_5_edge_case_lockout` | Unrequested Observed Action (Lockout Edge) | 1 statement (`s3:GetObject` only) | 1 action | 0 wildcards | `s3:GetObject` (10), `s3:PutObject` (5) (unpermitted write observed) |

---

## 3. Empirical Results Summary (50 Live Runs)

* **Automated Unit Tests:** **38 unit tests** (26 CLI + 12 Lambda), 100% passing.
* **Total Live Runs:** 50 (5 plans × 10 iterations)
* **Median End-to-End Latency:** **11.58 s**
* **P95 End-to-End Latency:** **21.54 s**
* **CloudWatch Stage Share of Total Latency:** **33.66%**

### CloudWatch Logs Insights Optimization (Before vs. After)
* **Baseline (Unoptimized):** Fixed 2.0 s polling interval and 7-day lookback window:
  * **Median:** **3.76 s** | **P95:** **6.53 s**
* **Optimized (Adaptive Polling & 48h Scoped Window):** Adaptive backoff starting at 100 ms (100 ms, 250 ms, 500 ms, 1 s):
  * **Median:** **0.74 s** | **P95:** **1.82 s**
* **Speedup Factor:** **5.1× faster** in the telemetry retrieval stage.

### Bedrock Nova Lite Token Counts & Operational Cost
* **Average Input Tokens per Run:** **261.4 tokens**
* **Average Output Tokens per Run:** **374.9 tokens**
* **Average Bedrock Cost per Run:** **$0.000106 USD**
* **Projected Cost per 1,000 Pipeline Analyses:** **~$0.1057 USD** (approx. 10.5 cents per 1,000 policy generations)

### Safety Layer Rejection Breakdown (50 Runs)
1. **Layer 1 (Deterministic AST Guard):** **2 interventions** (automatically pruned hallucinated or unobserved actions before Cedar validation).
2. **Layer 2 (Coverage Lockout Check):** **9 rejections** (blocked Plan 5 when the unrequested observed write action was dropped by the model, preventing application lockout).
3. **Layer 3 (Cedar Formal Verification in AVP):** **0 rejections** (all generated Cedar syntax conformed strictly to the registered Cedar schema).
4. **Layer 4 (IAM Access Analyzer Automated Reasoning):** **10 rejections** (rejected Plan 2 due to resource scope constraints during identity policy validation).
5. **Layer 5 (Human Approval):** **0 rejections** (interactive sign-off gate).

---

## 4. How to Deploy with AWS SAM

### Prerequisites
1. Python 3.12+
2. AWS SAM CLI installed (`sam --version`)
3. Configured AWS credentials (`aws sts get-caller-identity`)

### Deployment Steps
```bash
# 1. Navigate to infrastructure folder
cd infra

# 2. Configure SAM deployment parameters
cp samconfig.toml.example samconfig.toml
cp .env.example .env

# 3. Build serverless artifacts
sam build

# 4. Deploy stack to AWS
sam deploy --guided
```

---

## 5. System Limitations & Boundaries

1. **Resource ARN Wildcards:** The pipeline tightens IAM `Action` sets down to observed API calls, but retains the resource ARN from the requested baseline (e.g. `Resource: "*"` or specific bucket ARNs). Dynamic ARN synthesis from CloudTrail `requestParameters` is future work.
2. **Action Normalization Coverage:** Covers major S3, DynamoDB, SQS, and CloudWatch Logs CloudTrail-to-IAM API disparities. Arbitrary unmapped actions are handled defensively without widening to `*`.
3. **IAM Eventual Consistency:** AWS IAM updates (`iam:PutRolePolicy`) are eventually consistent. The CLI performs exponential backoff read-back checks with an `APPLIED_UNVERIFIED` fallback state if read-back takes longer than expected.
4. **Local Dashboard Loopback Security:** The live dashboard runs strictly on loopback `127.0.0.1` and validates Host and Origin headers to prevent DNS rebinding and cross-site scripting.
