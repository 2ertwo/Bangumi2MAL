from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import SyncItemResult, SyncRunResult


FIELDS = ["run_id", "result", "bangumi_id", "bangumi_title", "mal_id", "mal_title", "match_method", "match_confidence", "changes", "error"]


def _row(run_id: str, item: SyncItemResult) -> dict[str, object]:
    return {
        "run_id": run_id,
        "result": item.result,
        "bangumi_id": item.bangumi_id,
        "bangumi_title": item.bangumi_title,
        "mal_id": item.mal_id or "",
        "mal_title": item.mal_title,
        "match_method": item.match_method,
        "match_confidence": f"{item.match_confidence:.4f}",
        "changes": json.dumps(item.changes, ensure_ascii=False),
        "error": item.error,
    }


def export_run(run: SyncRunResult, reports_dir: Path) -> Path:
    run_dir = reports_dir / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    groups = {
        "synced.csv": [item for item in run.items if item.result in {"synced", "planned", "skipped"}],
        "unresolved.csv": [item for item in run.items if item.result in {"unresolved", "failed"}],
        "all.csv": run.items,
    }
    for filename, items in groups.items():
        with (run_dir / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(_row(run.run_id, item) for item in items)
    return run_dir
