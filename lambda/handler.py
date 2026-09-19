"""
Cedar Sentinel — Lambda Pipeline Processor (Phase 2: Core Reasoning & Verification)

Pipeline stages (each time-stamped into stage_timings):
  1. CloudWatch Logs Insights — query observed API calls for target role (7-day window)
  2. Bedrock reasoning       — draft Cedar policy + rationale from observed vs. requested
  3. Coverage / lockout check — block if any observed action is dropped from the draft
  4. Cedar formal verification — schema + validation via disposable AVP policy store

Result is written once to DynamoDB (cedar-sentinel-results) keyed by request_id,
then the CLI polls until status leaves PROCESSING.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────
# Environment / config
# ─────────────────────────────────────────────────────────────────
RESULTS_TABLE_NAME = os.environ.get("RESULTS_TABLE_NAME", "cedar-sentinel-results")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
CLOUDWATCH_LOG_GROUP_NAME = os.environ.get("CLOUDWATCH_LOG_GROUP_NAME", "")
AVP_POLICY_STORE_SSM_PARAM = os.environ.get(
    "AVP_POLICY_STORE_SSM_PARAM", "/cedar-sentinel/dev/avp-policy-store-id"
)
AVP_REGION = os.environ.get("AVP_REGION", os.environ.get("AWS_REGION", "ap-south-1"))
# ARN of Cedar Sentinel's own Lambda execution role — used to reject self-analysis
LAMBDA_EXECUTION_ROLE_ARN = os.environ.get("LAMBDA_EXECUTION_ROLE_ARN", "")

# Cedar Sentinel namespace used in all Cedar policies and schemas
CS_NAMESPACE = "CedarSentinel"

# Maximum Bedrock output tokens
BEDROCK_MAX_TOKENS = 2048

# CloudWatch Insights query lookback window in days
CWL_LOOKBACK_DAYS = 7

# Maximum seconds to wait for a CloudWatch Insights query to complete
CWL_QUERY_TIMEOUT_SECONDS = 60


# ─────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(time.time())


def _ttl_72h() -> int:
    return _now_unix() + (72 * 3600)


# ─────────────────────────────────────────────────────────────────
# Stage 1 — CloudWatch Logs Insights baseline query
# ─────────────────────────────────────────────────────────────────

def stage_cloudwatch_query(
    role_arn: str,
    log_group: str,
    region: str,
) -> Tuple[Dict[str, int], str, str]:
    """
    Queries CloudWatch Logs Insights for all API calls made by `role_arn`
    in the last CWL_LOOKBACK_DAYS days, aggregated as {eventName: count}.

    Returns (observed_actions, start_iso, end_iso).
    """
    start_iso = _now_iso()
    client = boto3.client("logs", region_name=region)

    end_time = int(time.time())
    start_time = end_time - (CWL_LOOKBACK_DAYS * 86400)

    # CloudTrail stores the assumed-role session ARN in userIdentity.arn, and
    # the underlying role ARN in userIdentity.sessionContext.sessionIssuer.arn.
    # We match against the session issuer field to reliably identify all sessions
    # that used the target role, regardless of session name.
    # We also capture eventSource so the caller can derive the service prefix
    # (e.g. "s3.amazonaws.com" → "s3") for correct Cedar action labels.
    query_string = (
        f'filter userIdentity.sessionContext.sessionIssuer.arn = "{role_arn}" '
        f"| stats count(*) as call_count by eventName, eventSource "
        f"| sort call_count desc "
        f"| limit 200"
    )

    logger.info(
        "Starting CloudWatch Logs Insights query for role '%s' on log group '%s'",
        role_arn,
        log_group,
    )

    start_resp = client.start_query(
        logGroupName=log_group,
        startTime=start_time,
        endTime=end_time,
        queryString=query_string,
    )
    query_id = start_resp["queryId"]

    # Poll until complete or timeout
    deadline = time.time() + CWL_QUERY_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(2)
        result_resp = client.get_query_results(queryId=query_id)
        status = result_resp.get("status", "")
        if status == "Complete":
            break
        if status in ("Failed", "Cancelled", "Timeout"):
            raise RuntimeError(f"CloudWatch Insights query {query_id} ended with status {status}")
    else:
        client.stop_query(queryId=query_id)
        raise TimeoutError(f"CloudWatch Insights query {query_id} timed out after {CWL_QUERY_TIMEOUT_SECONDS}s")

    # Parse results into {"service:EventName": count} map.
    # CloudTrail's eventSource is like "s3.amazonaws.com" — strip the ".amazonaws.com"
    # suffix to get the service prefix, then compose "service:EventName" so Cedar labels
    # are correct from the start (fixes the ssm:* / verifiedpermissions:* mislabeling bug).
    observed: Dict[str, int] = {}
    for row in result_resp.get("results", []):
        row_dict = {field["field"]: field["value"] for field in row}
        event_name = row_dict.get("eventName", "").strip()
        event_source = row_dict.get("eventSource", "").strip()
        count_str = row_dict.get("call_count", "0").strip()
        if event_name:
            # Derive service prefix: "verifiedpermissions.amazonaws.com" → "verifiedpermissions"
            service_prefix = event_source.replace(".amazonaws.com", "").replace(".aws", "")
            # Compose as "service:EventName" if we have a prefix, else keep bare eventName
            key = f"{service_prefix}:{event_name}" if service_prefix else event_name
            try:
                observed[key] = int(float(count_str))
            except ValueError:
                observed[key] = 0

    logger.info("CloudWatch query complete. Observed %d distinct API actions.", len(observed))
    end_iso = _now_iso()
    return observed, start_iso, end_iso


# ─────────────────────────────────────────────────────────────────
# Stage 2 — Bedrock reasoning call
# ─────────────────────────────────────────────────────────────────

def _invoke_bedrock_model_raw(
    client: Any,
    model_id: str,
    system_prompt: str,
    user_message: str,
) -> str:
    """Invokes a Bedrock model (Nova Lite, Anthropic, Meta Llama, or Mistral) and returns raw output string."""
    if "nova" in model_id or "amazon" in model_id.split("/")[-1]:
        # Amazon Nova models use the Converse-compatible messages API
        body = json.dumps({
            "messages": [{"role": "user", "content": [{"text": f"{system_prompt}\n\n{user_message}"}]}],
            "inferenceConfig": {
                "maxTokens": BEDROCK_MAX_TOKENS,
                "temperature": 0.1,
            },
        })
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        response_body = json.loads(response["body"].read())
        return response_body["output"]["message"]["content"][0]["text"].strip()

    elif "anthropic" in model_id:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": BEDROCK_MAX_TOKENS,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        })
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        response_body = json.loads(response["body"].read())
        return response_body["content"][0]["text"].strip()

    elif "llama" in model_id or "meta" in model_id:
        prompt = (
            f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
            f"{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{user_message}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        )
        body = json.dumps({
            "prompt": prompt,
            "max_gen_len": BEDROCK_MAX_TOKENS,
            "temperature": 0.1,
        })
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        response_body = json.loads(response["body"].read())
        return response_body.get("generation", "").strip()

    elif "mistral" in model_id:
        prompt = f"<s>[INST] {system_prompt}\n\n{user_message} [/INST]"
        body = json.dumps({
            "prompt": prompt,
            "max_tokens": BEDROCK_MAX_TOKENS,
            "temperature": 0.1,
        })
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        response_body = json.loads(response["body"].read())
        outputs = response_body.get("outputs", [])
        return outputs[0].get("text", "").strip() if outputs else ""

    else:
        # Generic fallback — try Nova-style messages API
        body = json.dumps({
            "messages": [{"role": "user", "content": [{"text": f"{system_prompt}\n\n{user_message}"}]}],
            "inferenceConfig": {
                "maxTokens": BEDROCK_MAX_TOKENS,
                "temperature": 0.1,
            },
        })
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        response_body = json.loads(response["body"].read())
        return response_body["output"]["message"]["content"][0]["text"].strip()


def stage_bedrock_call(
    requested_policy: Any,
    observed_actions: Dict[str, int],
    model_id: str,
    region: str,
    reevaluate_hint: str = "",
) -> Tuple[Dict[str, Any], str, str]:
    """
    Calls Bedrock to draft a tightened Cedar policy + rationale.

    Inputs:
      - requested_policy: the IAM policy document extracted from the Terraform plan
      - observed_actions:  {"service:EventName": count} from Stage 1 (already prefixed)
      - reevaluate_hint: optional hint from Option [3] retry

    Returns ({"cedar_policy": str, "rationale": str, "model_used": str}, start_iso, end_iso).
    """
    start_iso = _now_iso()
    logger.info("Resolved BEDROCK_MODEL_ID: %s", model_id)
    client = boto3.client("bedrock-runtime", region_name=region)

    # Build a compact representation of observed actions for the prompt
    observed_lines = "\n".join(
        f"  - {action}: {count} call(s)"
        for action, count in sorted(observed_actions.items(), key=lambda x: -x[1])
    ) or "  (no API calls observed in the lookback window)"

    requested_str = json.dumps(requested_policy, indent=2) if not isinstance(requested_policy, str) else requested_policy

    system_prompt = (
        "You are an expert cloud security policy engineer. Your job is to take an overly broad "
        "AWS IAM policy and produce a tighter Cedar policy that grants ONLY what the "
        f"principal actually needs, based on observed CloudTrail usage.\n"
        f"Use namespace '{CS_NAMESPACE}'.\n"
        "Output MUST be a single valid JSON object with exactly two keys: 'cedar_policy' (a string containing Cedar policy text) and 'rationale' (a string explaining changes).\n"
        "Example output format when observed actions exist:\n"
        "{\n"
        f'  "cedar_policy": "permit(\\n    principal,\\n    action in [\\n        {CS_NAMESPACE}::Action::\\"logs:CreateLogGroup\\",\\n        {CS_NAMESPACE}::Action::\\"logs:PutLogEvents\\"\\n    ],\\n    resource\\n);",\n'
        '  "rationale": "Tightened policy to include only observed CloudTrail actions."\n'
        "}\n\n"
        "Example output format for ZERO observed actions (empty list):\n"
        "{\n"
        f'  "cedar_policy": "forbid(\\n    principal,\\n    action in [\\n        {CS_NAMESPACE}::Action::\\"none\\"\\n    ],\\n    resource\\n);",\n'
        '  "rationale": "No API activity observed in the lookback window. Access denied by default."\n'
        "}\n\n"
        "Rules:\n"
        "1. 'cedar_policy' MUST be a STRING containing a single valid Cedar policy statement.\n"
        f"2. Every action must be formatted as '{CS_NAMESPACE}::Action::\"service:ActionName\"' — the service prefix is already included in each observed action string.\n"
        "3. When observed actions exist: output a single 'permit' statement listing all observed actions. Do NOT include a forbid statement.\n"
        f"4. When ZERO actions are observed: output a single 'forbid(principal, action in [{CS_NAMESPACE}::Action::\"none\"], resource);' statement. NEVER output free-text like 'deny all;'.\n"
        "5. Do NOT include markdown fences, code blocks, or text outside the JSON."
    )

    hint_section = f"\n\n## Feedback / Re-evaluation Hint\n{reevaluate_hint}" if reevaluate_hint else ""

    user_message = (
        f"## Requested IAM Policy (from Terraform plan)\n\n"
        f"```json\n{requested_str}\n```\n\n"
        f"## Observed CloudTrail API Actions (last {CWL_LOOKBACK_DAYS} days)\n\n"
        f"{observed_lines}"
        f"{hint_section}\n\n"
        "Draft a tightened Cedar policy that covers the observed actions and nothing more. "
        "Return ONLY the JSON object described in your instructions."
    )

    logger.info("Invoking Bedrock model '%s' for Cedar policy reasoning.", model_id)

    raw_text = ""
    actual_model_used = model_id
    try:
        raw_text = _invoke_bedrock_model_raw(client, model_id, system_prompt, user_message)
        logger.info("BEDROCK MODEL USED: %s", model_id)
    except Exception as exc:
        err_str = str(exc)
        logger.warning("Primary Bedrock model %s failed: %s", model_id, err_str)
        # Fallback to Meta Llama 3 70B if primary model is unavailable
        fallback_model = "meta.llama3-70b-instruct-v1:0"
        if model_id != fallback_model:
            logger.warning("FALLBACK MODEL USED: %s (primary model %s unavailable)", fallback_model, model_id)
            raw_text = _invoke_bedrock_model_raw(client, fallback_model, system_prompt, user_message)
            actual_model_used = fallback_model
        else:
            raise

    logger.info("Bedrock raw response (first 500 chars): %s", raw_text[:500])

    # Strip accidental markdown fences if present
    clean_text = raw_text.strip()
    if clean_text.startswith("```"):
        clean_text = re.sub(r"^```[a-z]*\n?", "", clean_text)
        clean_text = re.sub(r"\n?```$", "", clean_text.strip())

    parsed: Dict[str, Any] = {}
    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError:
        # Try extracting JSON object substring
        json_match = re.search(r"\{[\s\S]*\}", clean_text)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        if not parsed:
            # Resilient fallback: extract permit/forbid statement and rationale directly
            stmt_match = re.search(r'(permit\s*\([\s\S]*?\);|forbid\s*\([\s\S]*?\);)', clean_text)
            rat_match = re.search(r'"rationale"\s*:\s*"([^"]*)"', clean_text)
            if stmt_match:
                parsed = {
                    "cedar_policy": stmt_match.group(1).strip(),
                    "rationale": rat_match.group(1) if rat_match else "Tightened policy to include only observed CloudTrail actions.",
                }
            else:
                raise ValueError(
                    f"Bedrock response is not valid JSON and could not extract Cedar statement. Raw: {raw_text[:300]}"
                )

    if "cedar_policy" not in parsed or "rationale" not in parsed:
        raise ValueError(
            f"Bedrock JSON missing required keys. Got keys: {list(parsed.keys())}"
        )

    # Normalize cedar_policy to string if it was returned as a dict/list
    parsed["cedar_policy"] = _normalize_cedar_policy_text(parsed["cedar_policy"])
    # Attach the model that actually served this request
    parsed["model_used"] = actual_model_used

    end_iso = _now_iso()
    return parsed, start_iso, end_iso


# ─────────────────────────────────────────────────────────────────
# Stage 3 — Coverage / lockout hard-block check
# ─────────────────────────────────────────────────────────────────

def _normalize_cedar_policy_text(cedar_policy_raw: Any) -> str:
    """Ensures cedar_policy is a valid Cedar text string even if model returned a dict, list, or escaped string."""
    if isinstance(cedar_policy_raw, str):
        text = cedar_policy_raw
        if r'\"' in text:
            text = text.replace(r'\"', '"')
        if r'\n' in text and '\n' not in text:
            text = text.replace(r'\n', '\n')
        return text
    if isinstance(cedar_policy_raw, dict) or isinstance(cedar_policy_raw, list):
        raw_str = json.dumps(cedar_policy_raw)
        actions = []
        for m in re.finditer(r'Action::\\?"([^\\"]+)\\?"', raw_str):
            actions.append(m.group(1))
        if not actions:
            for m in re.finditer(r'\\?"([a-zA-Z0-9_*]+:[a-zA-Z0-9_*]+)\\?"', raw_str):
                actions.append(m.group(1))
        if actions:
            action_items = ",\n        ".join(f'{CS_NAMESPACE}::Action::"{a}"' for a in sorted(set(actions)))
            return f'permit(\n    principal,\n    action in [\n        {action_items}\n    ],\n    resource\n);'
        return json.dumps(cedar_policy_raw)
    return str(cedar_policy_raw)


def _extract_cedar_actions(cedar_policy_text: Any) -> List[str]:
    """
    Extracts the list of action strings from a Cedar policy text.
    Handles:
      action in [CS::Action::"s3:GetObject", ...]
      action in [CS::Action::\"s3:GetObject\", ...]
      action == CS::Action::"logs:PutLogEvents"
    Returns a list of action strings.
    """
    if not isinstance(cedar_policy_text, str):
        cedar_policy_text = _normalize_cedar_policy_text(cedar_policy_text)
    else:
        cedar_policy_text = _normalize_cedar_policy_text(cedar_policy_text)

    actions: List[str] = []
    pattern = re.compile(r'Action::\\?"([^\\"]+)\\?"')
    for match in pattern.finditer(cedar_policy_text):
        actions.append(match.group(1))

    if not actions:
        pattern2 = re.compile(r'\\?"([a-zA-Z0-9_*]+:[a-zA-Z0-9_*]+)\\?"')
        for match in pattern2.finditer(cedar_policy_text):
            actions.append(match.group(1))

    return list(set(actions))


def stage_coverage_check(
    observed_actions: Dict[str, int],
    cedar_policy_text: str,
) -> Tuple[Dict[str, Any], str, str]:
    """
    Compares observed actions (nonzero count) against the draft Cedar policy's
    allowed action set. If any observed action is missing → returns BLOCKED verdict.

    Returns (result_dict, start_iso, end_iso).
    result_dict keys: passed (bool), blocked_actions (list of {action, observed_count}).
    """
    start_iso = _now_iso()

    draft_actions = set(_extract_cedar_actions(cedar_policy_text))
    logger.info("Draft Cedar policy allows actions: %s", sorted(draft_actions))

    draft_actions_lower = {da.lower() for da in draft_actions}

    blocked = []
    for action, count in observed_actions.items():
        if count > 0:
            # Normalize: CloudTrail eventNames are like "GetObject"; Cedar uses "s3:GetObject"
            # Bedrock includes the service prefix. Compare case-insensitively.
            action_lower = action.lower()
            direct_match = action_lower in draft_actions_lower
            prefixed_match = any(
                da.endswith(f":{action_lower}") or da == action_lower
                for da in draft_actions_lower
            )
            if not direct_match and not prefixed_match:
                blocked.append({"action": action, "observed_count": count})

    result = {
        "passed": len(blocked) == 0,
        "blocked_actions": blocked,
    }

    if blocked:
        logger.warning(
            "Coverage check FAILED. %d observed action(s) dropped by draft policy: %s",
            len(blocked),
            [b["action"] for b in blocked],
        )
    else:
        logger.info("Coverage check PASSED — all observed actions present in draft policy.")

    end_iso = _now_iso()
    return result, start_iso, end_iso


# ─────────────────────────────────────────────────────────────────
# Stage 4 — Cedar formal verification via disposable AVP policy store
# ─────────────────────────────────────────────────────────────────

def _get_or_create_avp_store(
    ssm_client: Any,
    avp_client: Any,
    ssm_param: str,
) -> str:
    """
    Returns the ID of the disposable AVP policy store.
    Tries to read from SSM first; if missing or the store no longer exists,
    creates a new one and persists the ID.
    """
    store_id: Optional[str] = None

    # Try to read existing store ID from SSM
    try:
        resp = ssm_client.get_parameter(Name=ssm_param)
        candidate_id = resp["Parameter"]["Value"].strip()
        # Verify the store still exists
        avp_client.get_policy_store(policyStoreId=candidate_id)
        store_id = candidate_id
        logger.info("Reusing existing disposable AVP policy store: %s", store_id)
    except (ClientError, KeyError):
        pass  # SSM param missing or store deleted — fall through to create

    if store_id is None:
        create_resp = avp_client.create_policy_store(
            clientToken=f"cedar-sentinel-dev-{int(time.time())}",
            validationSettings={"mode": "STRICT"},
            description="Cedar Sentinel disposable validation store — safe to delete",
        )
        store_id = create_resp["policyStoreId"]
        logger.info("Created new disposable AVP policy store: %s", store_id)
        # Persist to SSM
        ssm_client.put_parameter(
            Name=ssm_param,
            Value=store_id,
            Type="String",
            Overwrite=True,
            Description="Cedar Sentinel disposable AVP policy store ID",
        )

    return store_id


def _build_cedar_schema(observed_actions: Dict[str, int], draft_actions: List[str]) -> Dict:
    """
    Builds a Cedar schema that enumerates all relevant actions from both the
    observed set and the draft policy. STRICT validation requires every action
    referenced in a policy to be declared in the schema.
    """
    # Collect all action names we need to declare
    all_actions: set = set()

    for action in observed_actions.keys():
        all_actions.add(action)

    for action in draft_actions:
        all_actions.add(action)

    # Build Cedar schema JSON (AVP format)
    actions_schema = {}
    for action in sorted(all_actions):
        actions_schema[action] = {
            "appliesTo": {
                "principalTypes": ["Role"],
                "resourceTypes": ["Resource"],
                "context": {"type": "Record", "attributes": {}},
            }
        }

    schema = {
        CS_NAMESPACE: {
            "entityTypes": {
                "Role": {
                    "memberOfTypes": [],
                    "shape": {"type": "Record", "attributes": {}},
                },
                "Resource": {
                    "memberOfTypes": [],
                    "shape": {"type": "Record", "attributes": {}},
                },
            },
            "actions": actions_schema,
        }
    }

    return schema


def stage_cedar_validation(
    cedar_policy_text: str,
    observed_actions: Dict[str, int],
    ssm_param: str,
    avp_region: str,
) -> Tuple[Dict[str, Any], str, str]:
    """
    Validates the Cedar policy text against the Cedar schema using a disposable
    AVP policy store. Uses PutSchema (STRICT mode) then attempts CreatePolicy —
    if AVP returns a validation error, the policy is invalid; if CreatePolicy
    succeeds, we immediately delete the created policy (the store stays, only the
    policy is cleaned up).

    Returns (result_dict, start_iso, end_iso).
    result_dict keys: passed (bool), messages (list of str), policy_store_id (str).
    """
    start_iso = _now_iso()

    ssm_client = boto3.client("ssm", region_name=avp_region)
    avp_client = boto3.client("verifiedpermissions", region_name=avp_region)

    store_id = _get_or_create_avp_store(ssm_client, avp_client, ssm_param)

    # Build and register the schema from observed + draft actions
    draft_actions = _extract_cedar_actions(cedar_policy_text)
    schema = _build_cedar_schema(observed_actions, draft_actions)

    logger.info("Registering Cedar schema on store %s (STRICT mode).", store_id)
    try:
        avp_client.put_schema(
            policyStoreId=store_id,
            definition={"cedarJson": json.dumps(schema)},
        )
    except ClientError as exc:
        # Schema PUT failed — possibly invalid schema structure
        end_iso = _now_iso()
        return (
            {
                "passed": False,
                "messages": [f"PutSchema failed: {exc.response['Error']['Message']}"],
                "policy_store_id": store_id,
            },
            start_iso,
            end_iso,
        )

    # Attempt CreatePolicy on the disposable store — this is the validation call.
    # AVP validates the policy text before storing; a validation failure returns
    # a 400 ValidationException without storing anything.
    logger.info("Validating draft Cedar policy via CreatePolicy on disposable store %s.", store_id)
    created_policy_id: Optional[str] = None
    passed = False
    messages: List[str] = []

    try:
        cp_resp = avp_client.create_policy(
            policyStoreId=store_id,
            definition={
                "static": {
                    "description": "cedar-sentinel-draft-validation",
                    "statement": cedar_policy_text,
                }
            },
        )
        created_policy_id = cp_resp["policyId"]
        passed = True
        messages = ["Policy passed STRICT Cedar schema validation."]
        logger.info("Cedar validation PASSED. Policy ID on disposable store: %s", created_policy_id)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg = exc.response["Error"]["Message"]
        passed = False
        messages = [f"{error_code}: {error_msg}"]
        logger.warning("Cedar validation FAILED: %s — %s", error_code, error_msg)

    # Clean up: delete the created policy from the disposable store if it was stored
    if created_policy_id:
        try:
            avp_client.delete_policy(
                policyStoreId=store_id,
                policyId=created_policy_id,
            )
            logger.info("Cleaned up disposable policy %s from store.", created_policy_id)
        except ClientError as exc:
            logger.warning("Could not clean up policy %s: %s", created_policy_id, exc)

    end_iso = _now_iso()
    return (
        {"passed": passed, "messages": messages, "policy_store_id": store_id},
        start_iso,
        end_iso,
    )


# ─────────────────────────────────────────────────────────────────
# DynamoDB result write
# ─────────────────────────────────────────────────────────────────

def write_result(
    table_name: str,
    request_id: str,
    status: str,  # COMPLETE | BLOCKED | ERROR
    region: str,
    role_arn: Optional[str] = None,
    observed_actions: Optional[Dict[str, int]] = None,
    cedar_policy: Optional[str] = None,
    rationale: Optional[str] = None,
    model_used: Optional[str] = None,
    requested_policy: Optional[Any] = None,
    coverage_check: Optional[Dict] = None,
    cedar_validation: Optional[Dict] = None,
    stage_timings: Optional[List[Dict]] = None,
    error_message: Optional[str] = None,
) -> None:
    """Writes the full pipeline result to DynamoDB. Called exactly once per request."""
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)

    item: Dict[str, Any] = {
        "request_id": request_id,
        "status": status,
        "ttl": _ttl_72h(),
        "completed_at": _now_iso(),
        "stage_timings": stage_timings or [],
    }

    if role_arn:
        item["role_arn"] = role_arn

    if observed_actions is not None:
        # DynamoDB doesn't allow int keys in maps — values are fine
        item["observed_actions"] = {k: str(v) for k, v in observed_actions.items()}

    if cedar_policy is not None:
        item["cedar_policy"] = cedar_policy

    if rationale is not None:
        item["rationale"] = rationale

    if model_used is not None:
        item["model_used"] = model_used

    if requested_policy is not None:
        item["requested_policy"] = (
            json.dumps(requested_policy)
            if not isinstance(requested_policy, str)
            else requested_policy
        )

    if coverage_check is not None:
        item["coverage_check"] = {
            "passed": coverage_check.get("passed", False),
            "blocked_actions": json.dumps(coverage_check.get("blocked_actions", [])),
        }

    if cedar_validation is not None:
        item["cedar_validation"] = {
            "passed": cedar_validation.get("passed", False),
            "messages": cedar_validation.get("messages", []),
            "policy_store_id": cedar_validation.get("policy_store_id", ""),
        }

    if error_message is not None:
        item["error_message"] = error_message

    table.put_item(Item=item)
    logger.info("Result written to DynamoDB table '%s' with status '%s'.", table_name, status)


# ─────────────────────────────────────────────────────────────────
# Main Lambda handler
# ─────────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Processes a single SQS message containing an EventBridge event from the CLI.
    Runs the four-stage reasoning + verification pipeline and writes the result
    to DynamoDB so the CLI can poll and display it.
    """
    records = event.get("Records", [])
    logger.info("Received SQS batch with %d record(s).", len(records))

    aws_region = os.environ.get("AWS_REGION", AVP_REGION)

    for record in records:
        message_id = record.get("messageId", "unknown")
        body_raw = record.get("body", "{}")

        logger.info("Processing SQS message ID: %s", message_id)

        try:
            body = json.loads(body_raw)
        except Exception:
            logger.error("Could not parse SQS body as JSON: %s", body_raw[:200])
            continue

        # Unwrap EventBridge envelope
        detail: Dict[str, Any] = {}
        if isinstance(body, dict) and "detail" in body:
            detail = body.get("detail", {})
        else:
            logger.warning("SQS body does not contain EventBridge 'detail' key. Skipping.")
            continue

        request_id = detail.get("request_id")
        if not request_id:
            logger.error("Event detail missing 'request_id'. Cannot write result. Skipping.")
            continue

        role_arn = detail.get("role_arn", "")
        # policies is a list; use the first one for the reasoning call
        policies = detail.get("policies", [])
        requested_policy = policies[0].get("policy_document") if policies else {}

        logger.info(
            "Starting pipeline for request_id='%s', role_arn='%s'",
            request_id,
            role_arn,
        )

        stage_timings: List[Dict] = []
        observed_actions: Dict[str, int] = {}
        bedrock_result: Dict[str, Any] = {}
        coverage_result: Dict[str, Any] = {}
        cedar_result: Dict[str, Any] = {}

        reevaluate_hint = detail.get("reevaluate_hint", "")

        try:
            # ── Stage 1: CloudWatch Logs Insights ──────────────────
            try:
                observed_actions, s1_start, s1_end = stage_cloudwatch_query(
                    role_arn=role_arn,
                    log_group=CLOUDWATCH_LOG_GROUP_NAME,
                    region=aws_region,
                )
                stage_timings.append(
                    {"stage": "cloudwatch_query", "start": s1_start, "end": s1_end}
                )
            except Exception as exc:
                logger.warning(
                    "CloudWatch query failed (%s). Proceeding with empty observed_actions map.", exc
                )
                s1_start = _now_iso()
                stage_timings.append(
                    {"stage": "cloudwatch_query", "start": s1_start, "end": _now_iso(), "error": str(exc)}
                )
                observed_actions = {}

            # ── Stage 2: Bedrock reasoning call ────────────────────
            bedrock_result, s2_start, s2_end = stage_bedrock_call(
                requested_policy=requested_policy,
                observed_actions=observed_actions,
                model_id=BEDROCK_MODEL_ID,
                region=aws_region,
                reevaluate_hint=reevaluate_hint,
            )
            stage_timings.append(
                {"stage": "bedrock_call", "start": s2_start, "end": s2_end}
            )

            cedar_policy_text: str = bedrock_result.get("cedar_policy", "")
            rationale: str = bedrock_result.get("rationale", "")
            model_used: str = bedrock_result.get("model_used", BEDROCK_MODEL_ID)

            # ── Stage 3: Coverage / lockout check ──────────────────
            coverage_result, s3_start, s3_end = stage_coverage_check(
                observed_actions=observed_actions,
                cedar_policy_text=cedar_policy_text,
            )
            stage_timings.append(
                {"stage": "coverage_check", "start": s3_start, "end": s3_end}
            )

            if not coverage_result["passed"]:
                # Hard block — do not proceed to Cedar verification
                logger.warning(
                    "Hard-block: coverage check failed. Writing BLOCKED result."
                )
                write_result(
                    table_name=RESULTS_TABLE_NAME,
                    request_id=request_id,
                    status="BLOCKED",
                    region=aws_region,
                    role_arn=role_arn,
                    observed_actions=observed_actions,
                    cedar_policy=cedar_policy_text,
                    rationale=rationale,
                    model_used=model_used,
                    requested_policy=requested_policy,
                    coverage_check=coverage_result,
                    cedar_validation=None,
                    stage_timings=stage_timings + [
                        {"stage": "cedar_validation", "start": _now_iso(), "end": _now_iso(), "skipped": True}
                    ],
                )
                continue  # next SQS record

            # ── Stage 4: Cedar formal verification ─────────────────
            cedar_result, s4_start, s4_end = stage_cedar_validation(
                cedar_policy_text=cedar_policy_text,
                observed_actions=observed_actions,
                ssm_param=AVP_POLICY_STORE_SSM_PARAM,
                avp_region=AVP_REGION,
            )
            stage_timings.append(
                {"stage": "cedar_validation", "start": s4_start, "end": s4_end}
            )

            # ── Write final result ──────────────────────────────────
            final_status = "COMPLETE" if cedar_result.get("passed", False) else "CEDAR_INVALID"
            if final_status == "CEDAR_INVALID":
                logger.warning(
                    "Cedar validation failed for request_id='%s'. Writing status 'CEDAR_INVALID'. Messages: %s",
                    request_id,
                    cedar_result.get("messages", []),
                )

            write_result(
                table_name=RESULTS_TABLE_NAME,
                request_id=request_id,
                status=final_status,
                region=aws_region,
                role_arn=role_arn,
                observed_actions=observed_actions,
                cedar_policy=cedar_policy_text,
                rationale=rationale,
                model_used=model_used,
                requested_policy=requested_policy,
                coverage_check=coverage_result,
                cedar_validation=cedar_result,
                stage_timings=stage_timings,
            )

        except Exception as exc:
            logger.exception("Unhandled exception for request_id='%s': %s", request_id, exc)
            write_result(
                table_name=RESULTS_TABLE_NAME,
                request_id=request_id,
                status="ERROR",
                region=aws_region,
                role_arn=role_arn,
                observed_actions=observed_actions,
                cedar_policy=bedrock_result.get("cedar_policy"),
                rationale=bedrock_result.get("rationale"),
                requested_policy=requested_policy,
                coverage_check=coverage_result or None,
                cedar_validation=None,
                stage_timings=stage_timings,
                error_message=str(exc),
            )

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Phase 2 pipeline batch processed", "records": len(records)}),
    }
