"""
Shared normalization and sanitization logic for Cedar Sentinel run data.
Used by scripts/export_run.py and cli/dashboard_server.py.
"""

import decimal
import json
import re
from typing import Any, Dict, List, Optional, Union


def decimal_default(obj: Any) -> Any:
    """Helper to serialize DynamoDB Decimal objects to int or float."""
    if isinstance(obj, decimal.Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def sanitize_value(val: Any, show_real_ids: bool = False) -> Any:
    """
    Recursively normalizes and optionally sanitizes sensitive AWS identifiers:
    - Normalizes JSON-encoded strings (requested_policy, previous_policy, iam_policy, blocked_actions)
    - Coerces observed_actions counts to integers
    - Drops 'ttl' field
    - Coerces Decimal to int/float
    
    If show_real_ids is False (default):
    - 12-digit AWS account IDs -> <ACCOUNT_ID>
    - Role/User ARNs keep role name but use <ACCOUNT_ID>
    - AVP policy store IDs (e.g. 22-char alphanumeric) -> <AVP_STORE_ID>
    - AVP policy IDs -> <POLICY_ID>
    - CloudTrail log group names (e.g. aws-cloudtrail-logs-...) -> <LOG_GROUP>
    """
    if isinstance(val, str):
        # 1. Check if string is a JSON object/array that should be parsed
        s_stripped = val.strip()
        if (s_stripped.startswith("{") and s_stripped.endswith("}")) or (s_stripped.startswith("[") and s_stripped.endswith("]")):
            try:
                parsed = json.loads(s_stripped)
                # If parsed is a dict/list, sanitize it recursively
                return sanitize_value(parsed, show_real_ids=show_real_ids)
            except Exception:
                pass

        if show_real_ids:
            return val

        # 2. CloudTrail log groups
        sanitized = re.sub(r"aws-cloudtrail-logs-[a-zA-Z0-9_-]+", "<LOG_GROUP>", val)
        # 3. Specific ARN replacements: keep resource name, replace account ID
        sanitized = re.sub(r"arn:aws:([a-zA-Z0-9-]+):([a-zA-Z0-9-]*):(\d{12}):", r"arn:aws:\1:\2:<ACCOUNT_ID>:", sanitized)
        # 4. Any remaining 12-digit account IDs
        sanitized = re.sub(r"\b\d{12}\b", "<ACCOUNT_ID>", sanitized)
        # 5. AVP policy store IDs (e.g. 22 chars base62 alphanumeric)
        sanitized = re.sub(r"\b[A-Za-z0-9]{22}\b", "<AVP_STORE_ID>", sanitized)
        return sanitized

    elif isinstance(val, dict):
        sanitized_dict = {}
        for k, v in val.items():
            if k == "ttl":
                continue

            # If observed_actions, coerce count strings to ints
            if k == "observed_actions" and isinstance(v, dict):
                sanitized_obs = {}
                for act_name, count_val in v.items():
                    act_key = act_name if show_real_ids else sanitize_value(act_name, show_real_ids=False)
                    try:
                        sanitized_obs[act_key] = int(count_val)
                    except (ValueError, TypeError):
                        sanitized_obs[act_key] = count_val
                sanitized_dict[k] = sanitized_obs
                continue

            # If coverage_check.blocked_actions is a JSON string, parse it
            if k == "coverage_check" and isinstance(v, dict):
                cov_dict = dict(v)
                if "blocked_actions" in cov_dict and isinstance(cov_dict["blocked_actions"], str):
                    try:
                        cov_dict["blocked_actions"] = json.loads(cov_dict["blocked_actions"])
                    except Exception:
                        pass
                sanitized_dict[k] = sanitize_value(cov_dict, show_real_ids=show_real_ids)
                continue

            # If policy_id or policy_store_id fields
            if not show_real_ids:
                if k in ("policy_id", "policyId") and isinstance(v, str):
                    sanitized_dict[k] = "<POLICY_ID>"
                    continue
                if k in ("policy_store_id", "policyStoreId") and isinstance(v, str):
                    sanitized_dict[k] = "<AVP_STORE_ID>"
                    continue

            sanitized_dict[k] = sanitize_value(v, show_real_ids=show_real_ids)
        return sanitized_dict

    elif isinstance(val, list):
        return [sanitize_value(v, show_real_ids=show_real_ids) for v in val]

    elif isinstance(val, decimal.Decimal):
        return int(val) if val % 1 == 0 else float(val)

    return val


def normalize_run_item(raw_item: Dict[str, Any], show_real_ids: bool = False, synthetic: Optional[bool] = None) -> Dict[str, Any]:
    """
    Normalizes a DynamoDB run item into the exact structure used by dashboard/runs/*.json.
    Ensures Decimal conversion, recursive sanitization/normalization, and consistent field presence.
    """
    clean_raw = json.loads(json.dumps(raw_item, default=decimal_default))
    sanitized = sanitize_value(clean_raw, show_real_ids=show_real_ids)
    if synthetic is not None:
        sanitized["synthetic"] = synthetic
    elif "synthetic" not in sanitized:
        sanitized["synthetic"] = False
    return sanitized
