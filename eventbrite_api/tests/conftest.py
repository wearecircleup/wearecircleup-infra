from __future__ import annotations

import os
from pathlib import Path


def pytest_collection_modifyitems(config, items):
    run_live_api = os.getenv("EVENTBRITE_LIVE_TEST") == "1"
    run_live_attendees = os.getenv("EVENTBRITE_LIVE_ATTENDEE_TEST") == "1"
    kept = []
    deselected = []

    for item in items:
        path = Path(str(item.fspath)).name
        if path == "test_live_api.py" and not run_live_api:
            deselected.append(item)
            continue
        if path == "test_live_attendees.py" and not run_live_attendees:
            deselected.append(item)
            continue
        kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
