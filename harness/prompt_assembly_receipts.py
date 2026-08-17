"""Private, content-free receipts for the existing prompt assembly gate.

This module observes the current policy.  It does not select, rank, truncate,
drop, render, submit, or retry prompt material.
"""
import copy
from datetime import datetime
import json
import os


def finalize_prompt_assembly_receipt(receipt, *, cycle_id, model_calls=()):
    """Return a detached turn-scoped receipt safe to expose or persist."""
    if not receipt:
        return None
    result = copy.deepcopy(receipt)
    result["cycle_id"] = str(cycle_id or "")
    # ISO's extended offset (``-04:00``) is accepted by the Python 3.10
    # runtime used by JNSQ.  The reader also preserves compatibility with
    # older receipts written with the basic ``-0400`` form.
    result["recorded_at"] = datetime.now().astimezone().isoformat(
        timespec="seconds")
    result["model_calls"] = copy.deepcopy(list(model_calls or ()))
    return result


def append_prompt_assembly_receipt(path, receipt):
    """Append and fsync one already-content-free receipt."""
    if not receipt:
        return False
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True
