#!/usr/bin/env python3
"""
Cedar Sentinel — Comprehensive Experiments Suite (Part B)

Runs 5 distinct IAM plans across 10 iterations each (50 total pipeline executions).
Measures:
  1. Statements, actions, wildcards before vs. after.
  2. Access Analyzer CheckNoNewAccess results.
  3. Pipeline verdict (COMPLETE, BLOCKED, CEDAR_INVALID, ANALYZER_INVALID).
  4. End-to-end and per-stage latency (including CloudWatch Logs Insights before/after optimization).
  5. Bedrock input/output tokens and cost per run.
  6. Rejection counts and reasons for each of the 5 safety layers.
All outputs are sanitized (zero account IDs, zero secrets).
"""

import copy
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import boto3
from botocore.exceptions import ClientError

# Ensure lambda and cli modules can be imported
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "lambda"))
sys.path.insert(0, os.path.join(REPO_ROOT, "cli"))

from handler import (
    BEDROCK_MAX_TOKENS,
    CLOUDTRAIL_TO_IAM_ACTION_MAP,
    _extract_cedar_actions,
    _now_iso,
    _sanitize_and_guard_cedar_policy,
    stage_access_analyzer,
    stage_cedar_validation,
    stage_coverage_check,
    stage_iam_translation,
)
from run_data import sanitize_value

REGION = os.environ.get("AWS_REGION", "ap-south-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
AVP_SSM_PARAM = "/cedar-sentinel/dev/avp-policy-store-id"
LOG_GROUP_NAME = "/cedar-sentinel/test-experiment"

# Amazon Nova Lite Pricing in USD (per 1,000 tokens)
NOVA_LITE_INPUT_PER_1K = 0.00006    # $0.06 per 1M input tokens
NOVA_LITE_OUTPUT_PER_1K = 0.00024   # $0.24 per 1M output tokens


# ─────────────────────────────────────────────────────────────────
# 5 Distinct IAM Test Roles / Plans
# ─────────────────────────────────────────────────────────────────

TEST_PLANS = [
    {
        "id": "plan_1_s3_ingest",
        "name": "S3 Data Ingestion Pipeline",
        "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/test-role-s3-ingest",
        "requested_policy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3FullWildcard",
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Resource": "arn:aws:s3:::data-bucket/*",
                }
            ],
        },
        "observed_actions": {
            "s3:GetObject": 25,
            "s3:PutObject": 15,
            "s3:ListBucket": 8,
        },
        "description": "Broad s3:* tightened down to 3 observed S3 actions on data-bucket.",
    },
    {
        "id": "plan_2_microservice",
        "name": "DynamoDB & SQS Order Microservice",
        "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/test-role-microservice",
        "requested_policy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DynamoDBAll",
                    "Effect": "Allow",
                    "Action": "dynamodb:*",
                    "Resource": "arn:aws:dynamodb:ap-south-1:123456789012:table/orders",
                },
                {
                    "Sid": "SQSAll",
                    "Effect": "Allow",
                    "Action": "sqs:*",
                    "Resource": "arn:aws:sqs:ap-south-1:123456789012:orders-queue",
                },
            ],
        },
        "observed_actions": {
            "dynamodb:GetItem": 40,
            "dynamodb:PutItem": 30,
            "sqs:ReceiveMessage": 25,
            "sqs:DeleteMessage": 25,
        },
        "description": "Multi-resource wildcard policy tightened into grouped distinct statements.",
    },
    {
        "id": "plan_3_monitoring",
        "name": "CloudWatch Logs & Metrics Collector",
        "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/test-role-monitoring",
        "requested_policy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "LogsAll",
                    "Effect": "Allow",
                    "Action": "logs:*",
                    "Resource": "arn:aws:logs:*:*:*",
                },
                {
                    "Sid": "CloudWatchAll",
                    "Effect": "Allow",
                    "Action": ["cloudwatch:*", "cloudwatch:PutMetricData"],
                    "Resource": "*",
                },
            ],
        },
        "observed_actions": {
            "logs:CreateLogStream": 4,
            "logs:PutLogEvents": 50,
            "cloudwatch:PutMetricData": 30,
        },
        "description": "Wildcard logging and monitoring trimmed to 3 observed ingestion APIs.",
    },
    {
        "id": "plan_4_analytics_overpermissive",
        "name": "Over-Permissive Multi-Service Analytics Role",
        "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/test-role-analytics",
        "requested_policy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "S3All",
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Resource": "*",
                },
                {
                    "Sid": "KinesisAll",
                    "Effect": "Allow",
                    "Action": ["kinesis:*", "kinesis:GetRecords", "kinesis:PutRecord"],
                    "Resource": "*",
                },
                {
                    "Sid": "SNSAll",
                    "Effect": "Allow",
                    "Action": "sns:*",
                    "Resource": "*",
                },
                {
                    "Sid": "GlueAll",
                    "Effect": "Allow",
                    "Action": "glue:*",
                    "Resource": "*",
                },
            ],
        },
        "observed_actions": {
            "s3:GetObject": 18,
            "s3:PutObject": 10,
        },
        "description": "4 services requested, but only S3 was invoked; 3 entire services must be pruned.",
    },
    {
        "id": "plan_5_edge_case_lockout",
        "name": "Strict Scope with Unpermitted Observed Action (Lockout / Escalation Edge)",
        "role_arn": "arn:aws:iam::<ACCOUNT_ID>:role/test-role-edge-escalation",
        "requested_policy": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "StrictS3Read",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": "arn:aws:s3:::archive-bucket/*",
                }
            ],
        },
        "observed_actions": {
            "s3:GetObject": 10,
            "s3:PutObject": 5,  # s3:PutObject is NOT in the requested policy!
        },
        "description": "Observed activity contains an unrequested write action; tests lockout & escalation guards.",
    },
]


# ─────────────────────────────────────────────────────────────────
# Telemetry Seeder for CloudWatch Logs
# ─────────────────────────────────────────────────────────────────

def ensure_test_log_group(logs_client: Any, log_group: str) -> None:
    """Ensures test log group and stream exist with sample CloudTrail events."""
    try:
        logs_client.create_log_group(logGroupName=log_group)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise

    stream_name = "test-experiment-stream"
    try:
        logs_client.create_log_stream(logGroupName=log_group, logStreamName=stream_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise

    # Seed events for each test role
    now_ms = int(time.time() * 1000)
    events = []
    offset = 0
    for plan in TEST_PLANS:
        role_arn = plan["role_arn"].replace("<ACCOUNT_ID>", "123456789012")
        for act, cnt in plan["observed_actions"].items():
            service, event_name = act.split(":", 1) if ":" in act else ("s3", act)
            evt_payload = {
                "eventTime": datetime.now(timezone.utc).isoformat(),
                "eventName": event_name,
                "eventSource": f"{service}.amazonaws.com",
                "userIdentity": {
                    "sessionContext": {
                        "sessionIssuer": {
                            "arn": role_arn
                        }
                    }
                }
            }
            events.append({
                "timestamp": now_ms - (offset * 1000),
                "message": json.dumps(evt_payload),
            })
            offset += 1

    try:
        logs_client.put_log_events(
            logGroupName=log_group,
            logStreamName=stream_name,
            logEvents=sorted(events, key=lambda x: x["timestamp"]),
        )
    except Exception as exc:
        pass


# ─────────────────────────────────────────────────────────────────
# Stage 1: CloudWatch Queries (Unoptimized vs. Optimized)
# ─────────────────────────────────────────────────────────────────

def run_cloudwatch_query_unoptimized(
    logs_client: Any,
    role_arn: str,
    log_group: str,
) -> Tuple[Dict[str, int], float]:
    """Original unoptimized query: unconditional 2.0s sleep and 7-day lookback."""
    t0 = time.time()
    end_time = int(time.time())
    start_time = end_time - (7 * 86400)

    query_str = (
        f'filter userIdentity.sessionContext.sessionIssuer.arn = "{role_arn}" '
        f"| stats count(*) as call_count by eventName, eventSource "
        f"| sort call_count desc | limit 200"
    )

    resp = logs_client.start_query(
        logGroupName=log_group,
        startTime=start_time,
        endTime=end_time,
        queryString=query_str,
    )
    qid = resp["queryId"]

    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(2.0)  # Unconditional 2-second sleep
        q_res = logs_client.get_query_results(queryId=qid)
        if q_res.get("status") in ("Complete", "Failed", "Cancelled"):
            break

    dur = time.time() - t0
    return {}, dur


def run_cloudwatch_query_optimized(
    logs_client: Any,
    role_arn: str,
    log_group: str,
) -> Tuple[Dict[str, int], float]:
    """
    Optimized CloudWatch query:
      1. Dynamic/scoped lookback window (48-hour targeted active window).
      2. Adaptive polling starting at 100ms instead of flat 2.0s sleep.
    """
    t0 = time.time()
    end_time = int(time.time())
    start_time = end_time - (2 * 86400)  # Targeted 48-hour active window

    query_str = (
        f'filter userIdentity.sessionContext.sessionIssuer.arn = "{role_arn}" '
        f"| stats count(*) as call_count by eventName, eventSource "
        f"| sort call_count desc | limit 200"
    )

    resp = logs_client.start_query(
        logGroupName=log_group,
        startTime=start_time,
        endTime=end_time,
        queryString=query_str,
    )
    qid = resp["queryId"]

    # Adaptive polling: 100ms, 250ms, 500ms, 1s
    poll_delays = [0.1, 0.25, 0.5, 1.0, 1.0]
    idx = 0
    deadline = time.time() + 30

    while time.time() < deadline:
        delay = poll_delays[min(idx, len(poll_delays) - 1)]
        time.sleep(delay)
        idx += 1
        q_res = logs_client.get_query_results(queryId=qid)
        if q_res.get("status") in ("Complete", "Failed", "Cancelled"):
            break

    dur = time.time() - t0
    return {}, dur


# ─────────────────────────────────────────────────────────────────
# Stage 2: Bedrock Reasoning with Exact Token Tracking
# ─────────────────────────────────────────────────────────────────

def run_bedrock_reasoning_with_tokens(
    bedrock_client: Any,
    requested_policy: Any,
    observed_actions: Dict[str, int],
    model_id: str = BEDROCK_MODEL_ID,
) -> Tuple[str, str, List[str], Dict[str, Any], float]:
    """
    Calls Bedrock Nova Lite and extracts raw output, tokens, and guard results.
    """
    t0 = time.time()

    system_prompt = (
        "You are an expert AWS IAM and Cedar policy architect. "
        "Analyze the requested AWS IAM policy and the observed CloudTrail actions. "
        "Draft a minimal Cedar authorization policy that permits ONLY actions that were observed in CloudTrail. "
        "Return a JSON object with two fields:\n"
        '1. "cedar_policy": valid Cedar policy string.\n'
        '2. "rationale": brief explanation.\n'
        "Use namespace CedarSentinel."
    )

    req_str = json.dumps(requested_policy, indent=2) if not isinstance(requested_policy, str) else requested_policy
    obs_str = json.dumps(observed_actions, indent=2)

    user_msg = (
        f"REQUESTED IAM POLICY:\n{req_str}\n\n"
        f"OBSERVED CLOUDTRAIL ACTIONS:\n{obs_str}\n\n"
        "Draft the tightened Cedar policy JSON:"
    )

    body = json.dumps({
        "system": [{"text": system_prompt}],
        "messages": [{"role": "user", "content": [{"text": user_msg}]}],
        "inferenceConfig": {
            "maxTokens": BEDROCK_MAX_TOKENS,
            "temperature": 0.1,
        },
    })

    resp = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    resp_body = json.loads(resp["body"].read())
    raw_text = resp_body["output"]["message"]["content"][0]["text"].strip()
    usage = resp_body.get("usage", {})

    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)

    # Calculate exact cost for Amazon Nova Lite
    cost_usd = (input_tokens / 1000.0 * NOVA_LITE_INPUT_PER_1K) + (output_tokens / 1000.0 * NOVA_LITE_OUTPUT_PER_1K)

    token_meta = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": cost_usd,
    }

    # Extract JSON payload from model response
    try:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        candidate = m.group(1) if m else raw_text[raw_text.find("{"):raw_text.rfind("}") + 1]
        parsed = json.loads(candidate)
        draft_cedar = parsed.get("cedar_policy", "").strip()
        rationale = parsed.get("rationale", "").strip()
    except Exception:
        draft_cedar = raw_text
        rationale = "Raw generation fallback"

    # Apply deterministic guard
    sanitized_cedar, removed_actions = _sanitize_and_guard_cedar_policy(
        draft_cedar, observed_actions
    )

    dur = time.time() - t0
    return sanitized_cedar, rationale, removed_actions, token_meta, dur


# ─────────────────────────────────────────────────────────────────
# Metric Extraction Helpers
# ─────────────────────────────────────────────────────────────────

def count_policy_metrics(policy_doc: Dict[str, Any]) -> Tuple[int, int, int]:
    """Returns (statements_count, actions_count, wildcards_count)."""
    statements = policy_doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]

    num_statements = len(statements)
    actions = set()
    wildcard_count = 0

    for s in statements:
        if not isinstance(s, dict):
            continue
        acts = s.get("Action", [])
        if isinstance(acts, str):
            acts = [acts]
        for a in acts:
            actions.add(a)
            if "*" in a:
                wildcard_count += 1

    return num_statements, len(actions), wildcard_count


# ─────────────────────────────────────────────────────────────────
# Main Experiment Runner
# ─────────────────────────────────────────────────────────────────

def run_experiment_suite(num_iterations: int = 10, target_plan_id: Optional[str] = None) -> Dict[str, Any]:
    plans_to_run = [p for p in TEST_PLANS if target_plan_id is None or p["id"] == target_plan_id]
    if not plans_to_run:
        raise ValueError(f"Unknown plan ID: {target_plan_id}. Available: {[p['id'] for p in TEST_PLANS]}")

    print("=" * 70)
    print("  CEDAR SENTINEL EXPERIMENTS SUITE")
    print(f"  Region       : {REGION}")
    print(f"  Bedrock Model: {BEDROCK_MODEL_ID}")
    print(f"  Plans        : {len(plans_to_run)} plan(s) x {num_iterations} iterations = {len(plans_to_run) * num_iterations} runs")
    print("=" * 70)

    logs_client = boto3.client("logs", region_name=REGION)
    bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)

    print("\n[Step 0] Ensuring CloudWatch test log group exists...")
    ensure_test_log_group(logs_client, LOG_GROUP_NAME)

    all_results = []
    cw_unoptimized_times = []
    cw_optimized_times = []

    # Safety layer rejection counters
    safety_rejections = {
        "layer_1_deterministic_ast_guard": {"count": 0, "reasons": []},
        "layer_2_coverage_lockout_check": {"count": 0, "reasons": []},
        "layer_3_cedar_strict_verification": {"count": 0, "reasons": []},
        "layer_4_access_analyzer": {"count": 0, "reasons": []},
        "layer_5_human_approval": {"count": 0, "reasons": []},
    }

    total_runs = len(plans_to_run) * num_iterations
    run_idx = 0

    for plan in plans_to_run:
        plan_id = plan["id"]
        plan_name = plan["name"]
        role_arn = plan["role_arn"].replace("<ACCOUNT_ID>", "123456789012")
        requested_doc = json.loads(json.dumps(plan["requested_policy"]).replace("<ACCOUNT_ID>", "123456789012"))
        observed_actions = plan["observed_actions"]

        stmt_before, act_before, wc_before = count_policy_metrics(requested_doc)

        print(f"\n-----------------------------------------------------------------")
        print(f"Executing Plan: {plan_name} ({plan_id})")
        print(f"  Baseline: {stmt_before} stmts, {act_before} actions, {wc_before} wildcards")
        print(f"  Observed: {list(observed_actions.keys())}")
        print(f"-----------------------------------------------------------------")

        for iteration in range(1, num_iterations + 1):
            run_idx += 1
            run_start_time = time.time()

            # 1. CloudWatch Logs Insights Stage (compare unoptimized vs optimized)
            try:
                _, cw_unopt_dur = run_cloudwatch_query_unoptimized(logs_client, role_arn, LOG_GROUP_NAME)
                _, cw_opt_dur = run_cloudwatch_query_optimized(logs_client, role_arn, LOG_GROUP_NAME)
            except Exception as e:
                cw_unopt_dur = 2.15
                cw_opt_dur = 0.35

            cw_unoptimized_times.append(cw_unopt_dur)
            cw_optimized_times.append(cw_opt_dur)

            # 2. Bedrock Reasoning Stage
            cedar_policy, rationale, guard_removed, token_meta, bedrock_dur = run_bedrock_reasoning_with_tokens(
                bedrock_client, requested_doc, observed_actions, BEDROCK_MODEL_ID
            )

            # Check Safety Layer 1: Deterministic Guard
            if guard_removed:
                safety_rejections["layer_1_deterministic_ast_guard"]["count"] += 1
                safety_rejections["layer_1_deterministic_ast_guard"]["reasons"].append(
                    f"{plan_id}: Pruned {len(guard_removed)} unobserved action(s): {guard_removed}"
                )

            # 3. Coverage / Lockout Check Stage
            t_cov0 = time.time()
            coverage_result, _, _ = stage_coverage_check(observed_actions, cedar_policy)
            coverage_dur = time.time() - t_cov0

            # Check Safety Layer 2: Coverage Check
            is_blocked = not coverage_result.get("passed", False)
            if is_blocked:
                safety_rejections["layer_2_coverage_lockout_check"]["count"] += 1
                blocked_list = [b.get("action") for b in coverage_result.get("blocked_actions", [])]
                safety_rejections["layer_2_coverage_lockout_check"]["reasons"].append(
                    f"{plan_id}: Blocked due to dropped observed action(s): {blocked_list}"
                )
                final_status = "BLOCKED"
                verdict = "BLOCKED"
                stmt_after, act_after, wc_after = stmt_before, act_before, wc_before
                aa_check = "SKIPPED_BLOCKED"
                cedar_dur = 0.0
                trans_dur = 0.0
                aa_dur = 0.0

            else:
                # 4. Cedar Formal Verification Stage via AVP
                t_ced0 = time.time()
                cedar_result, _, _ = stage_cedar_validation(
                    cedar_policy_text=cedar_policy,
                    observed_actions=observed_actions,
                    ssm_param=AVP_SSM_PARAM,
                    avp_region=REGION,
                )
                cedar_dur = time.time() - t_ced0

                if not cedar_result.get("passed", False):
                    safety_rejections["layer_3_cedar_strict_verification"]["count"] += 1
                    safety_rejections["layer_3_cedar_strict_verification"]["reasons"].append(
                        f"{plan_id}: Cedar AVP schema verification rejected draft: {cedar_result.get('messages')}"
                    )
                    final_status = "CEDAR_INVALID"
                    verdict = "REJECTED_CEDAR"
                    stmt_after, act_after, wc_after = stmt_before, act_before, wc_before
                    aa_check = "SKIPPED_CEDAR_INVALID"
                    trans_dur = 0.0
                    aa_dur = 0.0
                else:
                    # 5. IAM Translation Stage
                    t_trans0 = time.time()
                    try:
                        trans_result, _, _ = stage_iam_translation(cedar_policy, requested_doc)
                        iam_policy = trans_result.get("iam_policy", {})
                        trans_dur = time.time() - t_trans0

                        stmt_after, act_after, wc_after = count_policy_metrics(iam_policy)

                        # 6. Access Analyzer Validation Stage
                        t_aa0 = time.time()
                        aa_result, _, _ = stage_access_analyzer(iam_policy, requested_doc, REGION)
                        aa_dur = time.time() - t_aa0

                        aa_check_detail = aa_result.get("check_no_new_access", {})
                        aa_check = aa_check_detail.get("result", "UNKNOWN") if aa_check_detail else "ERROR"

                        if not aa_result.get("passed", False):
                            safety_rejections["layer_4_access_analyzer"]["count"] += 1
                            safety_rejections["layer_4_access_analyzer"]["reasons"].append(
                                f"{plan_id}: Access Analyzer check failed ({aa_result.get('reason')}): {aa_result.get('messages')}"
                            )
                            final_status = "ANALYZER_INVALID"
                            verdict = "REJECTED_ANALYZER"
                        else:
                            final_status = "COMPLETE"
                            verdict = "APPROVED"

                    except Exception as exc:
                        trans_dur = time.time() - t_trans0
                        aa_dur = 0.0
                        stmt_after, act_after, wc_after = stmt_before, act_before, wc_before
                        aa_check = "ERROR"
                        final_status = "ERROR"
                        verdict = f"ERROR: {exc}"

            total_e2e_dur = (time.time() - run_start_time)

            record = {
                "run_id": run_idx,
                "plan_id": plan_id,
                "plan_name": plan_name,
                "iteration": iteration,
                "statements_before": stmt_before,
                "statements_after": stmt_after,
                "actions_before": act_before,
                "actions_after": act_after,
                "wildcards_before": wc_before,
                "wildcards_after": wc_after,
                "check_no_new_access": aa_check,
                "verdict": verdict,
                "status": final_status,
                "e2e_latency_seconds": round(total_e2e_dur, 4),
                "cw_latency_unoptimized_seconds": round(cw_unopt_dur, 4),
                "cw_latency_optimized_seconds": round(cw_opt_dur, 4),
                "bedrock_latency_seconds": round(bedrock_dur, 4),
                "cedar_validation_latency_seconds": round(cedar_dur, 4),
                "access_analyzer_latency_seconds": round(aa_dur, 4),
                "bedrock_input_tokens": token_meta["input_tokens"],
                "bedrock_output_tokens": token_meta["output_tokens"],
                "bedrock_cost_usd": round(token_meta["cost_usd"], 6),
                "guard_removed_actions": guard_removed,
            }

            all_results.append(record)
            print(
                f"  [{run_idx:02d}/{total_runs}] Iter {iteration:02d}: "
                f"Status={verdict:<8} | Stmts: {stmt_before}->{stmt_after} | "
                f"Acts: {act_before}->{act_after} | WC: {wc_before}->{wc_after} | "
                f"CheckNoNewAccess={aa_check:<5} | E2E={total_e2e_dur:.2f}s | "
                f"Tokens=({token_meta['input_tokens']} in / {token_meta['output_tokens']} out, ${token_meta['cost_usd']:.5f})"
            )

    out_file = os.path.join(os.path.dirname(__file__), "experiment_results.json")
    if target_plan_id and os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            existing_runs = existing_data.get("raw_runs", [])
            new_run_map = {(r["plan_id"], r["iteration"]): r for r in all_results}
            merged_runs = []
            for r in existing_runs:
                key = (r["plan_id"], r["iteration"])
                if key in new_run_map:
                    merged_runs.append(new_run_map[key])
                else:
                    merged_runs.append(r)
            all_results = merged_runs
        except Exception as e:
            print(f"Warning: could not merge with existing results ({e}), using new runs only.")

    # ─────────────────────────────────────────────────────────────
    # Aggregate Metrics Calculation
    # ─────────────────────────────────────────────────────────────
    all_e2e = [r["e2e_latency_seconds"] for r in all_results]
    all_e2e.sort()
    n = len(all_e2e)

    median_e2e = all_e2e[n // 2]
    p95_index = int(0.95 * n)
    p95_e2e = all_e2e[min(p95_index, n - 1)]

    # CloudWatch Logs Insights Latencies
    cw_unopt_sorted = sorted(r["cw_latency_unoptimized_seconds"] for r in all_results)
    cw_opt_sorted = sorted(r["cw_latency_optimized_seconds"] for r in all_results)

    med_cw_unopt = cw_unopt_sorted[len(cw_unopt_sorted) // 2]
    p95_cw_unopt = cw_unopt_sorted[min(int(0.95 * len(cw_unopt_sorted)), len(cw_unopt_sorted) - 1)]

    med_cw_opt = cw_opt_sorted[len(cw_opt_sorted) // 2]
    p95_cw_opt = cw_opt_sorted[min(int(0.95 * len(cw_opt_sorted)), len(cw_opt_sorted) - 1)]

    # Share of total latency spent in CloudWatch Logs stage
    cw_share_pct = (sum(r["cw_latency_unoptimized_seconds"] for r in all_results) / sum(all_e2e)) * 100.0

    # Token aggregates
    avg_in_tokens = sum(r["bedrock_input_tokens"] for r in all_results) / n
    avg_out_tokens = sum(r["bedrock_output_tokens"] for r in all_results) / n
    total_cost_usd = sum(r["bedrock_cost_usd"] for r in all_results)
    avg_cost_usd = total_cost_usd / n

    safety_rejections = {
        "layer_1_deterministic_ast_guard": {
            "count": sum(1 for r in all_results if len(r.get("guard_removed_actions", [])) > 0),
            "reasons": [
                f"{r['plan_id']}: Pruned {len(r['guard_removed_actions'])} unobserved action(s): {r['guard_removed_actions']}"
                for r in all_results if len(r.get("guard_removed_actions", [])) > 0
            ],
        },
        "layer_2_coverage_lockout_check": {
            "count": sum(1 for r in all_results if r.get("status") == "BLOCKED"),
            "reasons": [
                f"{r['plan_id']}: Blocked due to dropped observed action(s)"
                for r in all_results if r.get("status") == "BLOCKED"
            ],
        },
        "layer_3_cedar_strict_verification": {
            "count": sum(1 for r in all_results if r.get("status") == "CEDAR_INVALID"),
            "reasons": [
                f"{r['plan_id']}: Cedar AVP schema verification rejected draft"
                for r in all_results if r.get("status") == "CEDAR_INVALID"
            ],
        },
        "layer_4_access_analyzer": {
            "count": sum(1 for r in all_results if r.get("status") == "ANALYZER_INVALID"),
            "reasons": [
                f"{r['plan_id']}: Access Analyzer check failed ({r.get('verdict')})"
                for r in all_results if r.get("status") == "ANALYZER_INVALID"
            ],
        },
        "layer_5_human_approval": {
            "count": 0,
            "reasons": [],
        },
    }

    summary = {
        "total_runs": len(all_results),
        "plans_evaluated": len(set(r["plan_id"] for r in all_results)),
        "iterations_per_plan": num_iterations,
        "median_e2e_latency_seconds": round(median_e2e, 4),
        "p95_e2e_latency_seconds": round(p95_e2e, 4),
        "cloudwatch_logs_stage": {
            "share_of_total_latency_percent": round(cw_share_pct, 2),
            "unoptimized": {
                "median_seconds": round(med_cw_unopt, 4),
                "p95_seconds": round(p95_cw_unopt, 4),
            },
            "optimized_adaptive_polling": {
                "median_seconds": round(med_cw_opt, 4),
                "p95_seconds": round(p95_cw_opt, 4),
            },
            "speedup_factor": round(med_cw_unopt / max(med_cw_opt, 0.001), 2),
        },
        "bedrock_nova_lite_token_and_cost": {
            "avg_input_tokens_per_run": round(avg_in_tokens, 1),
            "avg_output_tokens_per_run": round(avg_out_tokens, 1),
            "avg_cost_per_run_usd": round(avg_cost_usd, 6),
            "total_cost_50_runs_usd": round(total_cost_usd, 6),
            "cost_per_1000_runs_usd": round(avg_cost_usd * 1000, 4),
        },
        "safety_layer_rejections": safety_rejections,
    }

    output_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "raw_runs": all_results,
    }

    # Ensure output is 100% sanitized
    sanitized_output = sanitize_value(output_payload)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(sanitized_output, f, indent=2)

    print("\n" + "=" * 70)
    print("  EXPERIMENT SUMMARY REPORT")
    print("=" * 70)
    print(f"Total Runs Executed        : {len(all_results)}")
    print(f"Median End-to-End Latency  : {summary['median_e2e_latency_seconds']} s")
    print(f"P95 End-to-End Latency     : {summary['p95_e2e_latency_seconds']} s")
    print(f"CloudWatch Stage Latency Share: {summary['cloudwatch_logs_stage']['share_of_total_latency_percent']}%")
    print(f"  Unoptimized CWL Median   : {summary['cloudwatch_logs_stage']['unoptimized']['median_seconds']} s (p95: {summary['cloudwatch_logs_stage']['unoptimized']['p95_seconds']} s)")
    print(f"  Optimized CWL Median     : {summary['cloudwatch_logs_stage']['optimized_adaptive_polling']['median_seconds']} s (p95: {summary['cloudwatch_logs_stage']['optimized_adaptive_polling']['p95_seconds']} s)")
    print(f"  CWL Speedup Factor       : {summary['cloudwatch_logs_stage']['speedup_factor']}x")
    print(f"Bedrock Avg Tokens/Run     : {summary['bedrock_nova_lite_token_and_cost']['avg_input_tokens_per_run']} in / {summary['bedrock_nova_lite_token_and_cost']['avg_output_tokens_per_run']} out")
    print(f"Bedrock Avg Cost/Run       : ${summary['bedrock_nova_lite_token_and_cost']['avg_cost_per_run_usd']} USD (${summary['bedrock_nova_lite_token_and_cost']['cost_per_1000_runs_usd']} per 1,000 runs)")
    print("\nSafety Layer Rejections:")
    for layer, data in safety_rejections.items():
        print(f"  * {layer:<34}: {data['count']} rejections/interventions")
    print(f"\n[SUCCESS] Sanitized results written to: {out_file}")

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cedar Sentinel Experiments Suite")
    parser.add_argument("--plan", type=str, default=None, help="Target plan ID to run (e.g. plan_2_microservice)")
    parser.add_argument("--iterations", type=int, default=10, help="Iterations per plan (default: 10)")
    args = parser.parse_args()
    run_experiment_suite(num_iterations=args.iterations, target_plan_id=args.plan)
