"""
Cedar Sentinel — Lambda Pipeline Ingestion Handler (Phase 1 Scaffolding)
Consumes Terraform plan analysis events from SQS (delivered via EventBridge).
"""

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Processes batches of SQS messages containing EventBridge events.
    In Phase 1, logs the message payload and proves end-to-end connectivity.
    """
    records = event.get("Records", [])
    logger.info("Received SQS batch with %d record(s).", len(records))

    processed_count = 0
    for record in records:
        message_id = record.get("messageId")
        receipt_handle = record.get("receiptHandle")
        body_raw = record.get("body", "{}")

        logger.info("Processing SQS message ID: %s", message_id)

        try:
            body = json.loads(body_raw)
        except Exception:
            body = body_raw

        # EventBridge envelope inspection
        if isinstance(body, dict) and "detail" in body:
            source = body.get("source", "unknown")
            detail_type = body.get("detail-type", "unknown")
            detail = body.get("detail", {})
            logger.info(
                "EventBridge Event Dispatched -> Source: '%s', DetailType: '%s'",
                source,
                detail_type,
            )
            logger.info("Event Detail Payload: %s", json.dumps(detail, indent=2))
        else:
            logger.info("Raw Message Body: %s", json.dumps(body, indent=2) if isinstance(body, dict) else str(body))

        processed_count += 1

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Phase 1 event batch processed successfully",
            "processed_records": processed_count,
        }),
    }
