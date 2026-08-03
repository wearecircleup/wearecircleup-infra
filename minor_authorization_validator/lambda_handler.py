import json
import logging
import os
from typing import Any


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    logger.info(
        "Received minor authorization validation batch: %s",
        json.dumps(
            {
                "record_count": len(event.get("Records") or []),
                "jobs_table": os.getenv("AUTHORIZATION_JOBS_TABLE_NAME"),
                "youform_table": os.getenv("YOUFORM_SUBMISSIONS_TABLE_NAME"),
                "eventbrite_table": os.getenv("EVENTBRITE_ORDER_SUBMISSIONS_TABLE_NAME"),
            },
            ensure_ascii=False,
        ),
    )
    return {
        "ok": True,
        "record_count": len(event.get("Records") or []),
    }
