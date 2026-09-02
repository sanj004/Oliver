"""
Audit trail logging.
Every money-affecting decision the agent makes gets written here.
This satisfies the "explainable" + "show the audit trail" bar.
"""
import json
import os
from datetime import datetime, timezone
from config import LOGS_FILE


def log_event(action: str, input_data: dict, output_data: dict, decision_reason: str):
    """
    Append one structured audit entry.

    action:          short name of what happened, e.g. "search_products",
                      "create_order", "confirm_payment", "block_over_limit"
    input_data:       what was requested / passed in
    output_data:      what the system returned / decided
    decision_reason:  plain-English explanation of WHY this happened
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "input": input_data,
        "output": output_data,
        "reason": decision_reason,
    }
    logs = _read_logs()
    logs.append(entry)
    _write_logs(logs)
    return entry


def get_logs():
    return _read_logs()


def _read_logs():
    if not os.path.exists(LOGS_FILE):
        return []
    with open(LOGS_FILE, "r") as f:
        return json.load(f)


def _write_logs(logs):
    with open(LOGS_FILE, "w") as f:
        json.dump(logs, f, indent=2)