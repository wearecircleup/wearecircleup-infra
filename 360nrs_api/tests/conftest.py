from __future__ import annotations

import os
from pathlib import Path


def pytest_collection_modifyitems(config, items):
    run_live = os.getenv("NRS360_LIVE_TEST") == "1"
    kept = []
    deselected = []

    for item in items:
        path = Path(str(item.fspath)).name
        if path == "test_live_api.py" and not run_live:
            deselected.append(item)
            continue
        kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
